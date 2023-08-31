# PDK - Pachyderm | Determined | KServe
## Deployment and Setup Guide
**Date/Revision:** August 30, 2023


![alt text][big_picture]

[big_picture]: deploy/images/big_picture.png "Solution Big Picture"

&nbsp;
PDK is a platform that explores the synergy between 3 technologies, to provide end-to-end MLOps capabilities.  These technologies are:

### Pachyderm (also available as the HPE Machine Learning Data Management - MLDM Enterprise solution) 
is an open-source, enterprise grade data science platform that allows customers to deploy and manage multi-stage, language-agnostic data pipelines, while maintaining complete reproducibility and provenance. It provides virtually unlimited flexibility, as any type of data, from any type of source, can be processed with any type of code logic, developed in any language. All while keeping complete track of everything that happened with the data and the code, from beginning to end.

MLDM will be the data processing / data lineage / workflow coordinator component of the PDK flow. In the case of the samples provided here, MLDM waits for new files to be uploaded to a repository, so it can use them to train and deploy a new version of the model. This technology can, however, cover a myriad of other use cases, such as waiting until a certain amount of data is collected before training the model, collecting data from databases or message queues, re-training the model periodically, or waiting for some threshold condition (like high amounts of drift) before kicking off a re-training pipeline.


### Determined.AI (also available as the HPE Machine Learninng Development Environment - MLDE Enterprise solution)
is a platform designed to facilitate the training of Machine Learning models in a fast, easy and scalable way. It has three main goals: first, to allow model developers to leverage very complex capabilities, like distributed training, hyperparameter search, checkpointing (and others), in a very simple way, dramatically reducing the time and amount of code needed to train complex models. Second, it provides a user-friendly environment where model developers can organize their experiments into projects and collaborate with other users in a number of ways, reducing the learning curve and accelerating time to market. Thirdly, it abstracts the compute resources used to train the models, allowing users to very easily assign their workloads to the proper resources, like CPUs, GPUs, priority high-end servers, low-end test servers, etc. With MLDE, model developers don't need to play the role of platform administrators to secure the resources they need. 

MLDE will be the model training component of the PDK flow. It will receive the experiment definition directly from MLDM, in order to run in a fully automated fashion. Still, users will be able to fork experiments in order to test different settings or options.

### KServe
is a standard Model Inference Platform for Kubernetes, built for highly scalable use cases. It provides performant, standardized inference protocol across ML frameworks, including PyTorch, TensorFlow and Keras. Additionally, KServe provides features such as automatic scaling, monitoring, and logging, making it easy to manage deployed models in production. Advanced features, such as canary rollouts, experiments, ensembles and transformers are also available.

KServe will be the inference service component for the PDK. It will be responsible for serving predictions for the models that are trained by MLDE. In the PDK flow, MLDM will be responsible for deploying the models to KServe, once they are trained by MLDE.  

---

&nbsp;

Most MLOps platforms available today are built to provide a strong core functionality, while offering much weaker *satellite* capabilities to address the needs of ML Engineers and Data Scientists. The main differentiator of PDK is the fact that it brings together 3 best-of-breed technologies, each with its own very strong core. This creates a solution where each of its main pillars was designed from the ground up as an complete and comprehensive solution. The synergy between them makes PDK a platform greater than the sum of its parts.

A usual concern when it comes to platforms like PDK is about how cohesive this platform is, given that it's made up of different components. What makes PDK strong is the fact that each of these technologies was chosen for a reason; they have natural synergies between them that were already being leveraged well before PDK became an 'official' platform. In short, while this is a valid concern, especially for older technologies, it doesn't really apply to PDK, as these components offer very comprehensive integration and automation capabilities to enable an automated, end-to-end flow.

With PDK, customers get a comprehensive platform, while keeping risk and complexity low.

---

&nbsp;

The PDK environment provides end-to-end support for processing data that will be used to train and deploy Machine Learning models, in an automated fashion. Leveraging the workflow and automation capabilities of MLDM, the arrival of new data will initiate an Experiment in MLDE that will effectively re-train the model with the new data. MLDM will then deploy the best checkpoint from that experiment to KServe, so it can provide predictions to any client applications. With PDK, this flow can not only be automated, but it can be reproduced as needed, seeing as the data and all processing steps are correlated through unique IDs.


This repository includes step-by-step guides for installing the infrastructure and all necessary components for the PDK environment, covering different Kubernetes environments. This is an update to the original guide available [here](https://github.hpe.com/cyrill-hug/KServe-Addendum-for-PDS).

PS: Throughout the documents in this repository, Pachyderm will be referred to as **MLDM** (Machine Learning Data Management) and Determined.AI as **MLDE** (Machine Learning Development Environment).

The reference environment described here should not be seen as a suggestion for production and might need to be adjusted depending on use cases and performance requirements. 



This repository is divided in 4 parts:

1 - [Deploy the PDK components](deploy/README.md#deploy) to your platform of choice

2 - [Prepare the environment](deploy/README.md#setup) for the PDK flow (and deploy a sample model)

3 - [Access other examples](examples/) of PDK flows

4 - [Bring your own model](bring-your-own-model/readme.md) to PDK

&nbsp;


Click on the links above to get started with PDK.



## Authors/Owners
HPE AI At Scale SE team



## License
[MIT](https://choosealicense.com/licenses/mit/)

