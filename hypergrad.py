import tensorflow as tf
import numpy
import scipy.misc
import sys
import os

tf.set_random_seed(42)

#this is a basic linear model: noise ~ N(0,std),y ~ x*w + noise
class RegressionProblem():
    def __init__(self,config):

        self.dimension = config.dimension #dimension of x
        self.batchsize = config.batchsize #minibatch size during training
        self.stdev = config.stdev #noise variance in ground truth linear model. 

        self.do_conditioning = True #if we make the problem too easy, then optimization will be quite robust. 
        #For regression, the computational complexity of optimization on the train set, and the error on the test set, depend on the condition number of X'X
        #Therefore, to make good hyperparameter optimization more necessary, we (optionally) force the problem to be poorly conditioned

        self.input_placeholder = tf.placeholder('float',[self.batchsize,self.dimension],name='input',)
        self.true_params = [tf.Variable(numpy.random.randn(1,self.dimension).astype('float32'),name='true_params',trainable=False)] #parameters that the ground truth is generated with respect to
        self.init_params = [tf.zeros([1,self.dimension],name = 'regression_weights')] #initial guess for linear model parameters to learn
        #not that self.init_params does not contain the actual parameters that are learned (hence why it's not a tf.Variable above). 
        #The output of learn(), which essentially implements SGD learning as an RNN, is the learned parameters
       
        if(self.do_conditioning):
            d = numpy.random.rand(self.dimension)
            d[0] = 0.001 # to make it especially poorly conditioned, manually make one of the eigenvalues very small. 
            self.diag = numpy.diag(d)
            self.orth_matrix = numpy.linalg.svd(numpy.random.randn(self.dimension,self.dimension),compute_uv=True)[0] #this generates a random orthogonal matrix
            self.conditioning_matrix = self.orth_matrix*self.diag #this yields a warping of the space that will yield poorly-conditioned x. 
       
        #the train data is randomly sampled at each SGD step, but the dev and test sets are constant
        self.dev_data = tf.constant(self.transform(numpy.random.randn(10*self.batchsize,self.dimension)).astype('float32'))
        self.test_data = tf.constant(self.transform(numpy.random.randn(10*self.batchsize,self.dimension)).astype('float32'))

    #this warps the data with the conditioning matrix
    def transform(self,mat):
        if(self.do_conditioning):
            return numpy.dot(mat,self.conditioning_matrix)
        else:
            return mat

    #this generates a random batch of x variables for training            
    def gen_example(self): 
        return self.transform(numpy.random.randn(self.batchsize,self.dimension))

    #this predicts a batch of y, given a batch of x
    def predict(self,data,weights):
        return tf.matmul(data,weights[0],False,True)

    #under the linear model, samples from the true model can be generated by 'predicting' with the true parameters and then adding noise
    def generate(self,data,weights):
        predicted = self.predict(data,weights)
        noise = tf.random_normal(predicted.get_shape(),0,self.stdev)
        return predicted + noise

#utility function for logging a vector-valued quantity to be viewed in tensorboard. Is there a better way to do this than by using a scalar summary?
def logVector(writer,vector,session,name,dtype='float'):
    value = tf.placeholder(dtype,[])
    summary = tf.scalar_summary(name,value)
    for i,v in enumerate(vector):
        s = session.run(summary,feed_dict={value:v})
        writer.add_summary(s,i)
    writer.flush()

cl = tf.app.flags
cl.DEFINE_integer("num_epochs", 200, "Epoch to train")
cl.DEFINE_integer("num_train_steps", 25, "Gradient steps on train set")
cl.DEFINE_float("hyper_learning_rate", 0.05, "Learning rate of for adam [0.0002]")
cl.DEFINE_float("init_gamma", 0.9, "initial guess for momentum term")
cl.DEFINE_float("init_lr", 0.1, "initial guess for learning rate")
cl.DEFINE_boolean("learn_gamma", True, "Whether to optimize the momentum parameter")
cl.DEFINE_string("log_dir", './latest-log', "Place to write log files")
cl.DEFINE_float("dimension", 25, "dimensionality of regression problem")
cl.DEFINE_integer("batchsize", 320, "batchsize")
cl.DEFINE_float("stdev", 0.25, "noise variance in ground truth linear model")
config = cl.FLAGS

def main():
    if not os.path.exists(config.log_dir):
        os.makedirs(config.log_dir)

    problem = RegressionProblem(config)

    #This function performs SGD learning on the train set
    #It does SGD with momentum for fixed budget of numSteps gradient steps. It learns a separate learning rate for each step
    def learn(initialLr,gamma,init_params):
        #initalLR: initial guess for the value of the learned per-iteration learning rate
        #gamma: momentum decay term
        #init_params: initial guess for the model parameters

        cur_params = init_params
        learning_rates = []
        velocities = None

        for i in range(config.num_train_steps):
            lr_i = tf.Variable(initialLr,name='lr-{}'.format(i))
            learning_rates.append(lr_i)
            data = problem.input_placeholder
            truth = problem.generate(data,problem.true_params) #can't pull this out of the loop because it might be a different data subsample every time
            prediction = problem.predict(data,cur_params)
            op_loss = tf.reduce_mean(tf.square(prediction - truth),name='train-loss-{}'.format(i))
            grads = tf.gradients(op_loss, cur_params,name='learning-grad-{}'.format(i))
            if(not velocities):
                velocities = [tf.zeros_like(grad) for grad in grads]
            velocities = [gamma*v - (1- gamma)*g for (v,g) in zip(velocities,grads)]
            cur_params = [(p + lr_i*v) for p,v in zip(cur_params,velocities)]

        return cur_params, learning_rates

    #This evaluates the error on the a dataset
    def evaluate(cur_params, data,name):
        truth = problem.generate(data,problem.true_params)
        prediction = problem.predict(data,cur_params)
        op_loss = tf.reduce_mean(tf.square(prediction - truth),name = name)
        return op_loss    

    if(config.learn_gamma):
        gamma = tf.Variable(config.init_gamma,name='gamma')
        gamma_summary = tf.scalar_summary('gamma',gamma)
    else:
        gamma = config.init_gamma

    #this is the overall model. First, you learn on the train set, and then you evaluate on the dev set
    learned_params, learning_rates = learn(config.init_lr,gamma,problem.init_params)
    hyper_loss = evaluate(learned_params, problem.dev_data,'dev-loss')

    tvars = [] + learning_rates
    if(config.learn_gamma):
         tvars.append(gamma)
    
    #gradient of the dev loss with respect to the hyperparameters
    grads = tf.gradients(hyper_loss, tvars)
    optimizer = tf.train.AdagradOptimizer(config.hyper_learning_rate)
    op_optimize = optimizer.apply_gradients(zip(grads, tvars))

    #during the outer loop of learning our hyperparameters, we'll also evaluate our model on the test data
    op_evaluate = evaluate(learned_params,problem.test_data,'test-loss')

    dev_loss_summary = tf.scalar_summary('dev-loss',hyper_loss)
    test_loss_summary = tf.scalar_summary('test-loss',op_evaluate)
    loss_summaries = tf.merge_summary([dev_loss_summary,test_loss_summary])
    op_init = tf.initialize_all_variables()

    gd = tf.get_default_graph().as_graph_def()
    sw = tf.train.SummaryWriter(config.log_dir)
    sw.add_graph(gd) 

    with tf.Session() as session:
        session.run(op_init)
        for iteration in range(config.num_epochs):
            example = problem.gen_example()
            error, summary,_ = session.run([op_evaluate, loss_summaries,op_optimize], feed_dict={problem.input_placeholder: example})
            sw.add_summary(summary,iteration)
            print("%s: %s" % (iteration, error)) #this is the error on the test data
        
        #log the final learned learning rates and momentum parameter
        final_lrs = session.run(learning_rates)
        logVector(sw,final_lrs,session,'learning-rates')
        if(config.learn_gamma):
            sw.add_summary(session.run(gamma_summary),0)
        print('learned learning rates')
        print(final_lrs)
        print('learned momentum parameter')
        print(session.run(gamma))
    sw.flush()
    sw.close()

if __name__ == '__main__':
    main()
