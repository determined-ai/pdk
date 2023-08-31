![alt text][hpe_logo]

[hpe_logo]: images/hpe_logo.png "HPE Logo"


# PDK - Pachyderm | Determined | KServe
## Deployment Guide for Kubernetes


This guide will walk you through the steps of deploying the PDK components to a vanilla Kubernetes environment.


## Reference Architecture
The installation will be performed on the following hardware:

- 1x Control Plane - 8 CPU, 16GB RAM
- 1x worker node with 4 NVIDIA-T4 GPUs

The following software versions will be used for this installation:

- Ubuntu 20.04
- Kubernetes (K8s): 1.27.0
- Postgres: 13
- Determined.AI: 0.23.3
- Pachyderm: 2.6.5
- KServe: 0.10.0 (Quickstart Environment)

PS: some of the commands used here are sensitive to the version of the product(s) listed above.

## ***Attention: if are you planning to set this environment up in a cloud provider, please use the correspondent Kubernetes service instead (EKS for Amazon, GKE for Google, AKS for Azure). Using a VM-based kubernetes cluster in these cloud providers will cause unpredictable networking issues between the nodes, which will impact the PDK components.

If you are using AWS or GCP to deploy the cluster, please follow the [EKS](deploy_aws.md) or [GKE](deploy_gcp.md) guides instead. 

#### The environment used for this guide was deployed with MicroK8S (https://microk8s.io/docs), which is not a requirement for deploying PDK. Do keep in mind that some configurations might be different, depending on the Kubernetes distribution you are using.

## Prerequisites
To follow this documentation you will need:

- The following applications, installed and configured in your computer:
  - kubectl
  - docker (if you want to create and push images)
  - git (you'll need to be logged in to your github account to push code for the MLDM pipelines)
  - helm
  - jq
  - patchctl (the MLDM command line client)
  - det (the MLDE command line client)
- Access to a working Kubernetes cluster 
- GPU nodes configured in the cluster, with allocatable GPUs
- A shared folder that can be accessed by all nodes in the cluster (this example will use `/mnt/efs/shared_fs`)

&nbsp;


### This documentation assumes that that you have a functioning Kubernetes cluster (on a supported version), with one or more GPU nodes that have allocatable GPUs.

Postgres will be deployed to the cluster as part of this tutorial, but you can use an external Postgres instance instead.


--------

## Installing the PDK Components

In this page, we will execute the following steps:

[01 - Set Environment Variables](#step1)

[02 - Install and test the pre-req client applications](#step2)

[03 - Deploy Postgres to the cluster](#step3)

[04 - Create Postgres Databases](#step4)

[05 - Create Persistent Volumes for MLDM](#step5)

[06 - Create configuration .yaml file for MLDM](#step6)

[07 - Install MLDM using Helm](#step7)

[08 - Retrieve MLDM IP address and configure pachctl command line](#step8)

[09 - Prepare MLDE installation assets](#step9)

[10 - Deploy MLDE using Helm chart](#step10)

[11 - Retrieve MLDE IP address and configure det command line](#step11)

[12 - Deploy KServe](#step12)

[13 - (Optional) Test Components](#step13)

[14 - Prepare for PDK Setup](#step14)

[15 - Prepare Docker and the Registry to manage images](#step15)

[16 - Save data to Config Map](#step14)

<br/>

There is also a list of Kubernetes-specific [Useful Commands](#commands) at the bottom of the page.


#### NOTE: It's recommended to run these instructions one at a time, so you can diagnose in case of issues. The syntax for some of the commands documented here might become invalid, as new versions of these applications are released.


&nbsp;
<a name="step1">
### Step 1 - Set Environment Variables
</a>

All commands listed throghout this document must be executed in the same terminal window.

```bash
# MODIFY THESE VARIABLES
export NAME="your-name-pdk"
export DB_CONNECTION_STRING="postgres-service.default.svc.cluster.local."
export DB_ADMIN_PASSWORD="your-database-password"

export MLDM_NAMESPACE="pachyderm"
export KSERVE_MODELS_NAMESPACE="models"
```


&nbsp;
<a name="step2">
### Step 2 - Install and test the pre-req client applications
</a>

Install `pachctl` (the command line utility for MLDM):

```bash
curl -o /tmp/pachctl.deb -L https://github.com/pachyderm/pachyderm/releases/download/v2.6.8/pachctl_2.6.8_amd64.deb && sudo dpkg -i /tmp/pachctl.deb
```


Install `det` (the command line utility for MLDE):

```bash
pip install determined
```

Install `jq`:
```bash
sudo apt-get install -y jq
```


Make sure all these commands return successfully. If one of them fails, fix the issue before continuing.

```bash
kubectl version --client=true
helm version
pachctl version
det version
jq --version
```



&nbsp;
<a name="step3">
### Step 3 - Deploy Postgres to the cluster
</a>

If you are planning on using an external Postgres instance, you can skip this step.

For this exercise, Postgres will be deployed to the `default` namespace.

Create a Storage Class for Postgres:
```bash
kubectl apply -f  - <<EOF
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: manual
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: microk8s.io/hostpath
reclaimPolicy: Delete
parameters:
  pvDir: /mnt/efs/shared_fs
volumeBindingMode: WaitForFirstConsumer
EOF
```

PS: if you are not using MicroK8s, change the `provisioner` value to match your distribution.


Next, create the Persistent Volume:
```bash
kubectl apply -f  - <<EOF
kind: PersistentVolume
apiVersion: v1
metadata:
  name: postgres-pv
  labels:
    app: postgres
    type: local
spec:
  storageClassName: manual
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: "/mnt/efs/shared_fs/data"
EOF
```

Create the Persistent Volume Claim:
```bash
kubectl apply -f  - <<EOF
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: postgres-pv-claim
  labels:
    app: postgres
spec:
  storageClassName: manual
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
EOF
```

Create the Config Map for the Postgres instance:
```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
 name: postgres-configuration
 labels:
   app: postgres
data:
 POSTGRES_DB: postgres
 POSTGRES_USER: postgres
 POSTGRES_PASSWORD: ${DB_ADMIN_PASSWORD}
EOF
```

Create the Stateful Set:
```bash
kubectl apply -f  - <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-statefulset
  labels:
    app: postgres
spec:
  serviceName: "postgres"
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:13
        envFrom:
        - configMapRef:
            name: postgres-configuration
        ports:
        - containerPort: 5432
          name: postgresdb
        volumeMounts:
        - name: pv-data
          mountPath: /mnt/efs/shared_fs/postgres/
      volumes:
      - name: pv-data
        persistentVolumeClaim:
          claimName: postgres-pv-claim
EOF
```

Finally, create the Service:
```bash
k apply -f  - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
  labels:
    app: postgres
spec:
  ports:
  - port: 5432
    name: postgres
  type: NodePort 
  selector:
    app: postgres
EOF
```


List the services and get the IP assigned to the Postgres service:
```bash
ubuntu@ip-100-64-13-46:~$ kubectl get svc
NAME               TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)                     AGE
kubernetes         ClusterIP   10.152.183.1     <none>        443/TCP                     59m
operator-webhook   ClusterIP   10.152.183.171   <none>        9090/TCP,8008/TCP,443/TCP   44m
postgres-service   NodePort    10.152.183.67    <none>        5432:30955/TCP              23m
```

Make a note of the IP address for the Postgres service, as it will be used to connect to the instance.



&nbsp;
<a name="step4">
### Step 4 - Create Postgres Databases
</a>

Setup the 3 databases that will be used by PDK.  

Use the service's IP address to run a container with the `psql` utility, which will be used to create the databases. You could instead port-forward the Postgres service and use an external client like DBeaver.
```bash
kubectl run psql -it --rm=true --image=postgres:13 --command -- psql -h 10.152.183.67 -U postgres postgres
```

After running this command, you will see a message saying `If you don't see a command prompt, try pressing enter`. At this time, the psql utility is waiting for the password before connecting to the instance. Type in the postgres admin password and hit enter. If the command worked, you will see the `postgres#` prompt. Otherwise, delete the pod, check the IP address and try again.

Once connected to the instance, use these commands to create the databases:


```bash
CREATE DATABASE pachyderm;

CREATE DATABASE dex;

CREATE DATABASE determined;

GRANT ALL PRIVILEGES ON DATABASE pachyderm TO postgres;

GRANT ALL PRIVILEGES ON DATABASE dex TO postgres;

GRANT ALL PRIVILEGES ON DATABASE determined TO postgres;
```

PS: In this case, we'll be using the **postgress** user as the main user for MLDE and MLDM. You can create specific users for each product at this time, if needed.

You can get a list of databases by running the `\l` command:

```bash
postgres=# \l
                                 List of databases
    Name    |  Owner   | Encoding |  Collate   |   Ctype    |   Access privileges
------------+----------+----------+------------+------------+-----------------------
 determined | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =Tc/postgres         +
            |          |          |            |            | postgres=CTc/postgres
 dex        | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =Tc/postgres         +
            |          |          |            |            | postgres=CTc/postgres
 pachyderm  | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =Tc/postgres         +
            |          |          |            |            | postgres=CTc/postgres
 postgres   | postgres | UTF8     | en_US.utf8 | en_US.utf8 |
 template0  | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =c/postgres          +
            |          |          |            |            | postgres=CTc/postgres
 template1  | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =c/postgres          +
            |          |          |            |            | postgres=CTc/postgres
(6 rows)
```

When you're done, use the command `\q` to quit.



&nbsp;
<a name="step5">
### Step 5 - Create Persistent Volumes for MLDM
</a>

Make sure to have a working storage class. MLDM needs 2 persistent volumes to create the PVCs. They can have any names, as they will be dynamically bound to the PVCs during the MLDM deployment.

```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv1
  labels:
    type: local
spec:
  storageClassName: manual
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /mnt/efs/shared_fs/pv/pv1
EOF
```

&nbsp;
```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pv2
  labels:
    type: local
spec:
  storageClassName: manual
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /mnt/efs/shared_fs/pv/pv2
EOF
```


&nbsp;
<a name="step6">
### Step 6 - Create configuration .yaml file for MLDM
</a>

This command will create a .yaml file that you can review in a text editor.

```bash
cat <<EOF > mldm_values.yaml
deployTarget: "CUSTOM"
pachd:
  enabled: true
  externalService:
    enabled: true
  image:
    tag: "2.6.5"
  storage:
    backend: LOCAL
    local:
      hostPath: /mnt/efs/shared_fs/pachyderm
      requireRoot: true
etcd:
  storageClass: manual
  storageClassName: manual
  size: 10Gi
loki-stack:
  loki:
    securityContext:
      fsGroup: 0
      runAsGroup: 0
      runAsNonRoot: false
      runAsUser: 0  
    persistence:
      storageClassName: manual
      size: 10Gi
postgresql:
  enabled: false
global:
  postgresql:
    postgresqlHost: "${DB_CONNECTION_STRING}"
    postgresqlPort: "5432"
    postgresqlSSL: "disable"
    postgresqlUsername: "postgres"
    postgresqlPassword: "${DB_ADMIN_PASSWORD}"
proxy:
  enabled: true
  service:
    type: LoadBalancer
    httpPort: 9090
  tls:
    enabled: false
EOF
```


&nbsp;
<a name="step7">
### Step 7 - Install MLDM using Helm
</a>

First, download the charts for MLDM:

```bash
helm repo add pachyderm https://helm.pachyderm.com

helm repo update
```

Then create the namespace and run the installer, referencing the .yaml file you just created:

```bash
kubectl create ns ${MLDM_NAMESPACE}

helm install pachyderm -f ./mldm_values.yaml pachyderm/pachyderm --namespace ${MLDM_NAMESPACE}
```

Give it a couple of minutes for all the services to be up and running. You can run `kubectl -n ${MLDM_NAMESPACE} get pods` to see if any pods failed or are stuck. Wait until all pods are running before continuing.



&nbsp;
<a name="step8">
### Step 8 - Retrieve MLDM IP address and configure pachctl command line
</a>

In this step, we'll configure the pachctl client. This will be important later, as we create the project, repo and pipeline for the PDK environment.

```bash
export MLDM_HOST=$(kubectl get svc --namespace ${MLDM_NAMESPACE} pachyderm-proxy --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export MLDM_URL="http://${MLDM_HOST}:80"

echo $MLDM_URL

pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}
```

PS: You need a working URL to continue. Depending on how your cluster's networking is setup, you might need to run port forwarding in order to access the service.

At this time, the MLDM UI will be accessible:


![alt text][k8s_mldm_01_dashboard]

[k8s_mldm_01_dashboard]: images/k8s_mldm_01_dashboard.png "MLDM Dashboard"



&nbsp;
<a name="step9">
### Step 9 - Prepare MLDE installation assets
</a>

MLDE offers a hosted Jupyter Lab environment, where users can create and run notebooks. This environment needs persistent storage, in order to save user files. This persistent storage must be mounted as a shared folder. In this step, we will configure the necessary components to enable this capability.

First, make sure you have a storage class created. In this example, the storage class is called `manual`.

Run `kubectl get sc` to check the storageclasses available.

Now create two Persistent Volumes and two Persistent Volume Claims, one in each namespace that can run MLDE notebooks (*default* and *gpu-pool*). PS: We're setting it for 10GB, but you can increase the size as needed.

Run this command to create the first PV and PVC:
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mlde-pv
spec:
  storageClassName: manual
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  hostPath:
    path: "/mnt/efs/shared_fs/mlde_shared"
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: mlde-pvc
spec:
  storageClassName: manual
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
EOF
```

Next, create the second PV and PVC:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mlde-pv-gpu
spec:
  storageClassName: manual
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  hostPath:
    path: "/mnt/efs/shared_fs/mlde_shared"
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: mlde-pvc
  namespace: gpu-pool
spec:
  storageClassName: manual
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
EOF
```

You can validate that necessary components were created (and successfuly bound together) with the following commands:
```bash
kubectl get sc

kubectl get pv

kubectl get pvc

kubectl -n gpu-pool get pvc
```





Next, download and unzip the Helm chart for MLDE:

```bash
wget https://hpe-mlde.determined.ai/latest/_downloads/389266101877e29ab82805a88a6fc4a6/determined-latest.tgz

tar xvf determined-latest.tgz
```

PS: If this link doesn't work, you can download the latest Helm chart from this page:<br/>
https://hpe-mlde.determined.ai/latest/setup-cluster/deploy-cluster/k8s/install-on-kubernetes.html

Next, create a new values.yaml file for the Helm chart:

```bash
cat <<EOF > ./determined/values.yaml
imageRegistry: determinedai
enterpriseEdition: false
imagePullSecretName:
masterPort: 8080
useNodePortForMaster: false
db:
  hostAddress: "${DB_CONNECTION_STRING}"
  name: determined
  user: postgres
  password: ${DB_ADMIN_PASSWORD}
  port: 5432
checkpointStorage:
  saveExperimentBest: 0
  saveTrialBest: 1
  saveTrialLatest: 1
  type: shared_fs
  hostPath: /mnt/efs/shared_fs/determined
maxSlotsPerPod: 4
masterCpuRequest: 4
masterMemRequest: 8Gi
taskContainerDefaults:
  cpuImage: determinedai/environments:py-3.8-pytorch-1.12-tf-2.11-cpu-6eceaca
  gpuImage: determinedai/environments:cuda-11.3-pytorch-1.12-tf-2.11-gpu-6eceaca
  cpuPodSpec:
    apiVersion: v1
    kind: Pod
  gpuPodSpec:
    apiVersion: v1
    kind: Pod
    metadata:
      labels:
        nodegroup-role: gpu-worker
telemetry:
  enabled: true
resourcePools:
  - pool_name: default
    task_container_defaults:
      cpu_pod_spec:
        apiVersion: v1
        kind: Pod
        spec:
          containers:
            - name: determined-container
              volumeMounts:
                - name: shared-fs
                  mountPath: /run/determined/workdir/shared_fs
          volumes:
            - name: shared-fs
              persistentVolumeClaim:
                claimName: mlde-pvc        
  - pool_name: gpu-pool
    max_aux_containers_per_agent: 1
    kubernetes_namespace: gpu-pool
    task_container_defaults:
      gpu_pod_spec:
        apiVersion: v1
        kind: Pod
        spec:
          containers:
            - name: determined-container
              volumeMounts:
                - name: shared-fs
                  mountPath: /run/determined/workdir/shared_fs
          volumes:
            - name: shared-fs
              persistentVolumeClaim:
                claimName: mlde-pvc        
          tolerations:
            - key: "nvidia.com/gpu"
              operator: "Equal"
              value: "present"
              effect: "NoSchedule"
EOF
```


If your GPU node is not labeled, make sure to apply ther label before deploying MLDE:


```bash
kubectl label nodes <gpu-worker-node-name> node-role.kubernetes.io/gpu-worker=worker

kubectl label nodes <gpu-worker-node-name> nodegroup-role=gpu-worker
```


Create the gpu-pool namespace

```bash
kubectl create ns gpu-pool
```



&nbsp;
<a name="step10">
### Step 10 - Deploy MLDE using Helm chart
</a>

To deploy MLDE, run this command:

```bash
helm install determinedai ./determined
```

Because MLDE will be deployed to the default namespace, you can check the status of the deployment with `kubectl get pods` and `kubectl get svc`.<br/> 

Make sure the pod is running before continuing.


&nbsp;
<a name="step11">
### Step 11 - Retrieve MLDE IP address and configure det command line
</a>

Similar to the steps taken for MLDM, these commands will retrieve the load balancer address and create a URL we can use to access MLDE:

```bash
export MLDE_HOST=$(kubectl get svc determined-master-service-determinedai --output jsonpath='{.status.loadBalancer.ingress[0].ip}')

export MLDE_URL="http://${MLDE_HOST}:8080"

echo $MLDE_URL

export DET_MASTER=${MLDE_HOST}:8080
```
PS: As with MLDM, you may need to use port forwarding, depending on how your cluster's network is setup.


With the `DET_MASTER` environment variable set, you can run `det e list`, which should return an empty list. If you get an error message, check the MLDE pod and service for errors.

You should also be able to access the MLDE UI. Login as user **admin** (leave password field empty). Once logged in, check the **Cluster** page and make sure the GPU resources are showing up:


![alt text][k8s_mlde_01_ui]

[k8s_mlde_01_ui]: images/k8s_mlde_01_ui.png "MLDE UI - Clusters"



&nbsp;
<a name="step12">
### Step 12 - Deploy KServe
</a>

KServe is a standard Model Inference Platform on Kubernetes, built for highly scalable use cases. It provides performant, standardized inference protocol across ML frameworks, including PyTorch, TensorFlow and Keras.
Additionally, KServe provides features such as automatic scaling, monitoring, and logging, making it easy to manage deployed models in production. Advanced features, such as canary rollouts, experiments, ensembles and transformers are also available.
For more information on KServe, please visit [the official KServe documentation](https://kserve.github.io/website/0.9/).


Installation of KServe is very straightforward, because we are using the Quick Start. This is naturally only an option for test or demo environments;

```bash
curl -s "https://raw.githubusercontent.com/kserve/kserve/release-0.10/hack/quick_install.sh" | bash
```

After running this command, wait about 10 minutes for all the services to be properly initialized.



&nbsp;
<a name="step13">
### Step 13 - (Optional) Test Components
</a>

In this optional step, we can test MLDM (by creating a pipeline) and MLDE (by creating an experiment)

To test MLDM, run the following commands. They will create a new project, repo and pipeline, which will run for a few images we'll download.

```bash
pachctl create project openCV

pachctl config update context --project openCV

pachctl create repo images

pachctl list repo

wget http://imgur.com/46Q8nDz.png

pachctl put file images@master:liberty.png -f 46Q8nDz.png

pachctl list commit images

pachctl create pipeline -f https://raw.githubusercontent.com/pachyderm/pachyderm/2.6.x/examples/opencv/edges.json



wget http://imgur.com/8MN9Kg0.png

pachctl put file images@master:AT-AT.png -f 8MN9Kg0.png

wget http://imgur.com/g2QnNqa.png

pachctl put file images@master:kitten.png -f g2QnNqa.png

pachctl list commit images

pachctl create pipeline -f https://raw.githubusercontent.com/pachyderm/pachyderm/2.6.x/examples/opencv/montage.json

pachctl list job
```

&nbsp;

At this time, you should see the OpenCV project and pipeline in the MLDM UI:


![alt text][k8s_mldm_02_test_pipeline]

[k8s_mldm_02_test_pipeline]: images/k8s_mldm_02_test_pipeline.png "MLDM Test Pipeline"


&nbsp;

You should also be able to see the *chunks* in the shared folder. This confirms that MLDM is able to write to the storage location.


![alt text][k8s_mldm_03_chunks]

[k8s_mldm_03_chunks]: images/k8s_mldm_03_chunks.png "MLDM Storage Bucket"


PS: Do not modify or delete chunks, as it will break integrity.


&nbsp;

To test MLDE, you'll need to download the examples from the public github:

```bash

mkdir mlde_exp

cd mlde_exp

git clone https://github.com/determined-ai/determined.git .

```
&nbsp;
Once the command completes, run this command to modify the `./examples/computer_vision/cifar10_pytorch/const.yaml` file that will be used to run the experiment:

```bash
cat <<EOF > ./examples/computer_vision/cifar10_pytorch/const.yaml
name: cifar10_pytorch_const
environment:
  pod_spec:
    spec:
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Equal"
          value: "present"
          effect: "NoSchedule"
hyperparameters:
  learning_rate: 1.0e-4
  learning_rate_decay: 1.0e-6
  layer1_dropout: 0.25
  layer2_dropout: 0.25
  layer3_dropout: 0.5
  global_batch_size: 32
records_per_epoch: 500
searcher:
  name: single
  metric: validation_error
  max_length:
    epochs: 3
entrypoint: model_def:CIFARTrial
min_validation_period:
  epochs: 1
max_restarts: 0
resources:
  resource_pool: gpu-pool
  slots_per_trial: 2  
EOF
```

PS: We need to modify this file to ensure that this experiment will run in the GPU node pool. You can configure the node with taints that will reject workloads. In this case, you can set a toleration for this taint. We're also configuring the experiment to use 2 GPUs. And we're reducing the number of epochs to keep the training time short.

Use this command to run the experiment:

```bash
det experiment create -f ./examples/computer_vision/cifar10_pytorch/const.yaml ./examples/computer_vision/cifar10_pytorch
```
 If this command fails, make sure the `DET_MASTER` environment variable is set. For the first execution, the client might time out while it's waiting for the image to be pulled from docker hub. It does not mean the experiment has failed; you can still check the UI or use `det e list` to see the current status of this experiment.


&nbsp;

Your experiment will appear under Uncategorized (we will change that for the PDK experiments). You can track the Experiment log to see if there are any issues.


![alt text][k8s_mlde_04_test_experiment]

[k8s_mlde_04_test_experiment]: images/k8s_mlde_04_test_experiment.png "MLDE Experiment"


&nbsp;

You can also check the MLDE files in the shared folder, to see the checkpoints that were saved:


![alt text][k8s_mlde_05_storage]

[k8s_mlde_05_storage]: images/k8s_mlde_05_storage.png "MLDE Storage Bucket"

This confirms that MLDE is able to access the shared storage folder as well.



&nbsp;
<a name="step14">
### Step 14 - Prepare for PDK Setup
</a>

These next steps will help us verify that KServe is working properly, and they will also setup some pre-requisites for the PDK flow (specifically, the step where models are deployed to KServe).

A deeper explanation of the P-D-K flow is provided in the [main page](readme.md); for now, let's make sure KServe is working as expected.

Models deployed to KServe will run in pods that will be created in the `${KSERVE_MODELS_NAMESPACE}` namespace. This namespace can be created by running this command:

```bash
kubectl create ns ${KSERVE_MODELS_NAMESPACE}
```

Next, we will test KServe by deploying a sample model. This can be done by running the following command:

```bash
kubectl apply -n ${KSERVE_MODELS_NAMESPACE} -f - <<EOF
apiVersion: "serving.kserve.io/v1beta1"
kind: "InferenceService"
metadata:
  name: "sklearn-iris"
spec:
  predictor:
    sklearn:
      storageUri: "gs://kfserving-examples/models/sklearn/1.0/model"
EOF
```

Give it a minute and check the status of the InferenceService:

```bash
kubectl get inferenceservices sklearn-iris -n ${KSERVE_MODELS_NAMESPACE}
```

It should go from **Unknown** to **Ready**, which means the deployment was successful.

```bash
ubuntu@ip-100-64-13-46:~$ kubectl get inferenceservices sklearn-iris -n ${KSERVE_MODELS_NAMESPACE}
NAME           URL                                      READY   PREV   LATEST   PREVROLLEDOUTREVISION   LATESTREADYREVISION                    AGE
sklearn-iris   http://sklearn-iris.models.example.com   True           100                              sklearn-iris-predictor-default-00001   60s

```

Next, check the IP address for the Ingress:

```bash
kubectl get svc istio-ingressgateway -n istio-system

export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice sklearn-iris -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME
```

Make sure the command output includes a public IP. Fix any issues before continuing.


```bash
ubuntu@ip-100-64-13-46:~$ export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
ubuntu@ip-100-64-13-46:~$ export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')
ubuntu@ip-100-64-13-46:~$ export SERVICE_HOSTNAME=$(kubectl get inferenceservice sklearn-iris -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)
ubuntu@ip-100-64-13-46:~$ echo $INGRESS_HOST
192.168.1.1
ubuntu@ip-100-64-13-46:~$ echo $INGRESS_PORT
80
ubuntu@ip-100-64-13-46:~$ echo $SERVICE_HOSTNAME
sklearn-iris.models.example.com
```

Next, we'll create a simple input file that we can use to test this model (by generating a prediction):

```bash
cat <<EOF > "./iris-input.json"
{
  "instances": [
    [6.8,  2.8,  4.8,  1.4],
    [6.0,  3.4,  4.5,  1.6]
  ]
}
EOF
```

Then, use this command to generate the prediction:

```bash
curl -v -H "Host: ${SERVICE_HOSTNAME}" http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/sklearn-iris:predict -d @./iris-input.json
```

What we're looking for in the ouput is a status code of 200 (success) and a JSON payload with a list of values:


![alt text][k8s_kserve_02_prediction]

[k8s_kserve_02_prediction]: images/k8s_kserve_02_prediction.png "KServe Sample Prediction"



Make sure you get a valid response before continuing, as the deployment will fail if KServer is not properly setup.

The last part of this step is basically some housekeeping tasks to set the stage for the PDK flow.

First, we create a secret that will store variables that will be used by both MLDM pipelines and MLDE experiments. In this case, we'll use internal hostnames, as all these components are running in the same cluster:

```bash
export MLDE_SVC=determined-master-service-determinedai.default.svc.cluster.local
export MLDM_SVC=pachyderm-proxy.${MLDM_NAMESPACE}.svc.cluster.local

cat <<EOF > "./pipeline-secret.yaml"
apiVersion: v1
kind: Secret
metadata:
  name: pipeline-secret
stringData:
  det_master: "${MLDE_SVC}:8080"
  det_user: "admin"
  det_password: ""
  pac_token: ""
  pachd_lb_service_host: "${MLDM_SVC}"
  pachd_lb_service_port: "80"
  kserve_namespace: "${KSERVE_MODELS_NAMESPACE}"
EOF
```
Alternatively, you could use the external IP address for these services.


A more detailed explanation of these attributes:

- `det_master`: The address to the MLDE instance. Instead of using a URL, you can also point it to the service running in the default namespace (`determined-master-service-determinedai`).
- `det_user`: MLDE user that will create experiments and pull models.
- `det_password`: Password to the user specified above
- `pac_token`: For the Enterprise version of Pachyderm, create an authentication token for a user. Otherwise, if you use the community edition, leave it blank.
- `kserve_namespace`: Namespace where MLDM will deploy the models trained by MLDE.

&nbsp;

This secret needs to be created in the MLDM namespace, as it will be used by the pipelines (that will then map the variables to the MLDE experiment):

```bash
kubectl -n ${MLDM_NAMESPACE} apply -f pipeline-secret.yaml
```

Next, the MLDM Worker service account (which will be used to run the pods that contain the pipeline code) needs to gain access to the `${KSERVE_MODELS_NAMESPACE}` namespace, or it won't be able to deploy models there.

First, create the configuration file:

```bash
cat <<EOF > "./mldm-kserve-perms.yaml"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kserve-inf-service-role
  namespace: ${KSERVE_MODELS_NAMESPACE}
  labels:
    app: kserve-inf-app
rules:
- apiGroups: ["serving.kserve.io"]
  resources: ["inferenceservices"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: role-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kserve-inf-service-role
subjects:
- kind: ServiceAccount
  name: pachyderm-worker
  namespace: ${MLDM_NAMESPACE}
EOF
```

Then apply it:

```bash
kubectl apply -f mldm-kserve-perms.yaml
```


The next step is to create dummy credentials to allow access to the MLDM repo through the S3 protocol.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: pach-kserve-creds
  namespace: ${KSERVE_MODELS_NAMESPACE}
  annotations:
    serving.kserve.io/s3-endpoint: pachd.${MLDM_NAMESPACE}:30600
    serving.kserve.io/s3-usehttps: "0" 
type: Opaque
stringData: 
  AWS_ACCESS_KEY_ID: "dummycredentials"
  AWS_SECRET_ACCESS_KEY: "dummycredentials" 
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pach-deploy
  namespace: ${KSERVE_MODELS_NAMESPACE}
  annotations:
    serving.kserve.io/s3-endpoint: pachd.${MLDM_NAMESPACE}:30600
    serving.kserve.io/s3-usehttps: "0" 
secrets:
- name: pach-kserve-creds
EOF
```




&nbsp;
<a name="step15">
### Step 15 - Prepare Docker and the Registry to manage images
</a>

For this step, make sure Docker Desktop is running.

In order to create your own PDK flows, you will need a Registry where you can deploy the images you create. Vanilla Kubernetes installations will usually rely on Docker Registry, though there are many other options, including the Cloud providers. Because of that, this guide will not provide instructions on how to configure a Registry.

If you are unsure how to configure a Registry, the Google Cloud Artifact Registry service allows you to make repositories public, by granting read access to `allUsers`:

![alt text][k8s_registry_01_repository]

[k8s_registry_01_repository]: images/k8s_registry_01_repository.png "Google Cloud Artifact Registry"


Once you have a Registry available, follow these instructions to push your images to it.

First, set the Registry path in the `${REGISTRY_URI}` variable. For Google Artifact Registry, this path is usually:<br/> `<region>-docker.pkg.dev/<project_id>/<repository_name>`

The next commands will pull the busybox image (as an example), tag it and push it to the Registry.

```bash
docker pull busybox:latest

aws ecr create-repository --repository-name=${NAME}/busybox --region ${AWS_REGION}

docker tag busybox:latest ${REGISTRY_URI}/busybox

docker push ${REGISTRY_URI}/busybox
```

Check the output for error messages. An EOF message means the image failed to be uploaded. In this case, retry the push command.

You can check the Registry to make sure the new image is there.



&nbsp;
<a name="step16">
### Step 16 - Save data to Config Map
</a>

Now that all components are installed, we need a location to place some of the variables we've been using for the deployment. This config map can be used when configuring the PDK flows.

Create the configuration file:

```bash
cat <<EOF > ./pdk-config.yaml
kind: ConfigMap
apiVersion: v1
metadata:
  name: pdk-config
  namespace: default
data:
  region: "US"
  mldm_namespace: "${MLDM_NAMESPACE}"
  mldm_bucket_name: "/mnt/efs/shared_fs/pachyderm"
  mldm_host: "${MLDM_HOST}"
  mldm_port: "80"
  mldm_url: "${MLDM_URL}"
  mldm_pipeline_secret: "pipeline-secret"
  mlde_bucket_name: "/mnt/efs/shared_fs/determined"
  mlde_host: "${MLDE_HOST}"
  mlde_port: "8080"
  mlde_url: "${MLDE_URL}"
  kserve_model_bucket_name: "N/A"
  kserve_model_namespace: "${KSERVE_MODELS_NAMESPACE}"
  kserve_ingress_host: "${INGRESS_HOST}"
  kserve_ingress_port: "${INGRESS_PORT}"
  db_connection_string: "${DB_CONNECTION_STRING}"
  registry_uri: "${REGISTRY_URI}"
  pdk_name: "${NAME}"
EOF
```

Next, create the configmap:

```bash
kubectl apply -f ./pdk-config.yaml
```

Once the config map is created, you can run `kubectl get cm pdk-config -o yaml` to verify the data.


&nbsp;

&nbsp;
<a name="commands">
## Kubernetes - Useful Commands
</a>

### Grant Access to Shared Folders

This command will grant read+write access to the shared folder structure. It might be useful if you see permission errors in your pods.

```bash
sudo find /mnt/efs/shared_fs \( -type d -exec sudo chmod u+rwx,g+rwx,o+rx {} \; -o -type f -exec sudo chmod u+rw,g+rw,o+r {} \; \)
```

&nbsp;
### Test and Restart CoreDNS

If you notice DNS resolution errors in the pod logs, you can create a pod to test DNS resolution inside your cluster:

```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: dnsutils
  namespace: default
spec:
  containers:
  - name: dnsutils
    image: registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3
    command:
      - sleep
      - "infinity"
    imagePullPolicy: IfNotPresent
  restartPolicy: Always
EOF
```

Then, check DNS resolution for any service in your cluster using this command:

```bash
kubectl exec -i -t dnsutils -- nslookup <service>.<namespace>.svc.cluster.local
```

Example:

```bash
ubuntu@ip-100-64-13-46:~$ kubectl exec -i -t dnsutils -- nslookup pg-bouncer.pachyderm.svc.cluster.local
Server:		10.152.183.10
Address:	10.152.183.10#53

Name:	pg-bouncer.pachyderm.svc.cluster.local
Address: 10.152.183.104
```

If this command works, but the pod is still complaining about DNS resolution, use this command to restart Core DNS. Then restart the pod that is throwing the errors.

```bash
kubectl -n kube-system rollout restart deploy coredns
```

&nbsp;
### Allocatable GPUs

Use this command to verify the allocatable GPUs in your cluster:

```bash
kubernetes describe nodes  |  tr -d '\000' | sed -n -e '/^Name/,/Roles/p' -e '/^Capacity/,/Allocatable/p' -e '/^Allocated resources/,/Events/p'  | grep -e Name  -e  nvidia.com  | perl -pe 's/\n//'  |  perl -pe 's/Name:/\n/g' | sed 's/nvidia.com\/gpu:\?//g'  | sed '1s/^/Node Available(GPUs)  Used(GPUs)/' | sed 's/$/ 0 0 0/'  | awk '{print $1, $2, $3}'  | column -t
```

Make sure Available is greater than zero for your GPU node(s).

&nbsp;
### Port Forwarding

Depending on your cluster setup, you might need to port forward. If your cluster is runnign inside VMs, you might need to port forward twice (from the pod to the VM, then to your desktop). These commands show how to run port forward twice, for MLDE and MLDM (just use the second one if you are not installing on VM environments).

```bash
MLDE:
ssh -L 8080:127.0.0.1:8080 -i "key.pem" ubuntu@kube-node-host 
kubectl -n default port-forward svc/determined-master-service-determinedai 8080:8080

MLDM:
ssh -L 9090:127.0.0.1:9090 -i "key.pem" ubuntu@kube-node-host 
kubectl -n ${MLDM_NAMESPACE} port-forward svc/pachyderm-proxy 9090:9090

```

You will then be able to access these services through a `http://localhost:<port>` URL.




&nbsp;

---

&nbsp;

The installation steps are now completed. At this time, you have a working cluster, with MLDM, MLDE and KServe deployed. 

Next, return to [the main page](README.md) to go through the steps to prepare and deploy the PDK flow for the dogs-and-cats demo.

<br/><br/>