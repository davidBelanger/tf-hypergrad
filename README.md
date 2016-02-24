# tf-hypergrad
This is a simple example of gradient-based hyperparameter optimization, as discussed in Maclaurin, Duvenaud, and Adams' "Gradient-based Hyperparameter Optimization through Reversible Learning" [link](http://arxiv.org/pdf/1502.03492.pdf). We consider a simple linear regression model. 

We learn per-iteration step sizes and a momentum parameter by differentiating the dev set loss. The dev set loss depends on the learned parameters, so we back-propagate through the process of learning the parameters using sgd with momentum. Essentially, the learning process is represented as an unrolled computation graph. See the paper and the comments in the code for more explanation.  This was intended mainly as a means for me to learn tensorflow. If you have any suggestions, please let me know. 

Use the --log_dir option to specify where to write out logging information. Then, you can visualize lots of diagnostics in tensorboard, including the very long computation graph representing learning. 

