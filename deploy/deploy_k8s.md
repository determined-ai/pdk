![alt text][hpe_logo]

[hpe_logo]: images/hpe_logo.png "HPE Logo"


# PDK - Pachyderm | Determined | KServe
## Deployment Guide for Kubernetes
<b>Date/Revision:</b> February 23, 2024


This guide will walk you through the steps of deploying the PDK components to a vanilla Kubernetes environment.


## Reference Architecture
The installation will be performed on the following hardware:

- 1x Control Plane - 32 CPU, 64GB RAM, 1000GB storage
- 1x worker node with 4 NVIDIA-T4 GPUs, 1000GB storage

The following software versions will be used for this installation:

- Ubuntu 20.04
- Python: 3.8 and 3.9
- Kubernetes (K8s): latest supported *(currently 1.27)*
- Postgres: 13
- MLDE (Determined.AI): latest *(currently 0.28.1)*
- MLDM (Pachyderm): latest *(currently 2.8.4)*
- KServe: 0.12.0-rc0 (Quickstart Environment)

PS: some of the commands used here are sensitive to the version of the product(s) listed above.

## ***Attention: if are you planning to set this environment up in a cloud provider, please use the correspondent Kubernetes service instead (EKS for Amazon, GKE for Google, AKS for Azure). Using a VM-based kubernetes cluster in these cloud providers will cause unpredictable networking issues between the nodes, which will impact the PDK components.

If you are using AWS or GCP to deploy the cluster, please follow the [EKS](deploy_aws.md) or [GKE](deploy_gcp.md) guides instead.

#### The environment used for this guide was deployed with MicroK8S (https://microk8s.io/docs), which is not a requirement for deploying PDK. Do keep in mind that some configurations might be different, depending on the Kubernetes distribution you are using.

## Prerequisites
To follow this documentation you will need:

- The following applications, installed and configured in your computer:
  - kubectl
  - docker (if you want to create and push images)
  - git (to clone the repository with the examples)
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

[03 - Configure Node Labels and Taints](#step3)

[04 - Deploy Postgres to the cluster](#step4)

[05 - Create Postgres Databases](#step5)

[06 - Create Persistent Volumes for MLDM & Deploying MinIO](#step6)

[07 - Create configuration .yaml file for MLDM](#step7)

[08 - Install MLDM using Helm](#step8)

[09 - Retrieve MLDM IP address and configure pachctl command line](#step9)

[10 - Prepare MLDE installation assets](#step10)

[11 - Deploy MLDE using Helm chart](#step11)

[12 - Retrieve MLDE IP address and configure det command line](#step12)

[13 - Deploy KServe](#step13)

[14 - (Optional) Test Components](#step14)

[15 - Prepare for PDK Setup](#step15)

[16 - [Optional] Configure KServe UI](#step16)

[17 - Prepare Docker and the Registry to manage images](#step17)

[18 - Save data to Config Map](#step18)

<br/>

There is also a list of Kubernetes-specific [Useful Commands](#commands) at the bottom of the page.


#### NOTE: It's recommended to run these instructions one at a time, so you can diagnose in case of issues. The syntax for some of the commands documented here might become invalid, as new versions of these applications are released.


&nbsp;
<a name="step1">
### Step 1 - Set Environment Variables
</a>

All commands listed throghout this document must be executed in the same terminal window.

```bash
# Set the name of your cluster
export NAME="your-name-pdk"

# Generate admin password for MLDE (or set your own password)
export ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -dc A-Za-z0-9 | head -c16)

# Default name for namespace where models will be deployed to
export KSERVE_MODELS_NAMESPACE="models"

# Modify if using external Postgres DB
export DB_CONNECTION_STRING="postgres-service.default.svc.cluster.local."

# Optionally, set a different password for the database:
export DB_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
```


&nbsp;
<a name="step2">
### Step 2 - Install and test the pre-req client applications
</a>

Install `pachctl` (the command line utility for MLDM):

```bash
curl -L https://github.com/pachyderm/pachyderm/releases/download/v2.8.2/pachctl_2.8.2_linux_amd64.tar.gz | sudo tar -xzv --strip-components=1 -C /usr/local/bin
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
### Step 3 - Configure Node Labels and Taints
</a>

This might be a good time to validate that your cluster has the proper labels in place, along with the Taint that will prevent non-model training workloads to run on the GPU node. Check the list of nodes and configure each according to its role:

```bash
kubectl get nodes -o wide

kubectl label nodes admin-node-name nodegroup-role=control-plane

kubectl label nodes --overwrite admin-node-name node-role.kubernetes.io/control-plane=admin

kubectl label nodes gpu-node-name nodegroup-role=gpu-worker

kubectl label nodes --overwrite gpu-node-name node-role.kubernetes.io/gpu-worker=worker

kubectl taint nodes gpu-node-name nvidia.com/gpu=present:NoSchedule
```
PS: make sure to replace `gpu-node-name` and `admin-node-name` with the names of your nodes.

PS: if you have control plane nodes, along with CPU and GPU nodes, make sure to taint the control plane nodes so no pod are allocated there. That way, all products will be deployed to the CPU nodes and the GPU nodes will be reserved to run MLDE workloads.




&nbsp;
<a name="step4">
### Step 4 - Deploy Postgres to the cluster
</a>

If you are planning on using an external Postgres instance, you can skip this step.

For this exercise, Postgres will be deployed to the `default` namespace.


First, create the Persistent Volume:
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
kubectl apply -f  - <<EOF
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
postgres-service   NodePort    10.152.183.67    <none>        5432:30955/TCP              23m
```

Make a note of the IP address for the Postgres service, as it will be used to connect to the instance.



&nbsp;
<a name="step5">
### Step 5 - Create Postgres Databases
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
<a name="step6">
### Step 6 - Create Persistent Volumes for MLDM & Deploy MinIO
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
  capacity:
    storage: 10Gi
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
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: /mnt/efs/shared_fs/pv/pv2
EOF
```

&nbsp;

MLDM requires an object storage. For on-prem environments, we can use MinIO. Use the commands below to deploy MinIO.

**Important**: We're limiting this storage to 50GB, since this is a test/POC environment. You can change this setting as needed.

Create the Persistent Volume:
```bash
kubectl apply -f  - <<EOF
kind: PersistentVolume
apiVersion: v1
metadata:
  name: minio-pv
  labels:
    app: minio
    type: local
spec:
  capacity:
    storage: 50Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: "/mnt/efs/shared_fs/minio"
EOF
```

Create the Persistent Volume Claim:
```bash
kubectl apply -f  - <<EOF
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: minio-pvc
  labels:
    app: minio
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi
EOF
```

Create the StatefulSet:
```bash
kubectl apply -f  - <<EOF
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: minio
  labels:
    app: minio
spec:
  selector:
    matchLabels:
      app: minio
  serviceName: "minio"
  replicas: 1
  template:
    metadata:
      labels:
        app: minio
    spec:
      terminationGracePeriodSeconds: 10
      containers:
      - name: minio
        image: docker.io/minio/minio:latest
        command: ["/bin/bash"]
        # this will create a bucket called "mldm-bucket" and then launch minio
        args: ["-c", "mkdir -p /data/mldm-bucket && mkdir -p /data/mlde-bucket && mkdir -p /data/kserve-bucket && minio server /data --console-address=0.0.0.0:9001" ]
        securityContext:
          runAsUser: 1000
          runAsGroup: 1000
        ports:
        - containerPort: 9000
          name: s3
        - containerPort: 9001
          name: console
        volumeMounts:
        - name: minio-data
          mountPath: /data
      volumes:
        - name: minio-data
          persistentVolumeClaim:
            claimName: minio-pvc
EOF
```

Create the Service:
```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: minio
  labels:
    app: minio
spec:
  ports:
  - port: 9000
    name: s3
  - port: 9001
    name: console
  type: NodePort
  selector:
    app: minio
EOF
```

You can check the MinIO log with this command:
```bash
kubectl logs -f minio-0
```

&nbsp;

Because we're also running the MinIO console, the user interface will be accessible through port 9001:


![alt text][k8s_minio_01_ui]

[k8s_minio_01_ui]: images/k8s_minio_01_ui.png "MinIO Main UI"

Login as `minioadmin/minioadmin`. You will also see the buckets created by the StatefulSet. We'll use these buckets to store the MLDM objects, along with MLDE checkpoints and models for KServe.



&nbsp;
<a name="step7">
### Step 7 - Deploy KServe
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
<a name="step8">
### Step 8 - Prepare MLDE installation assets
</a>

MLDE offers a hosted Jupyter Lab environment, where users can create and run notebooks. This environment needs persistent storage, in order to save user files. This persistent storage must be mounted as a shared folder. In this step, we will configure the necessary components to enable this capability.

Create two Persistent Volumes and two Persistent Volume Claims, one in each namespace that can run MLDE notebooks (*default* and *gpu-pool*). PS: We're setting it for 200GB, but you can increase the size as needed.

Run this command to create the first PV and PVC:
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mlde-pv
spec:
  capacity:
    storage: 200Gi
  accessModes:
    - ReadWriteMany
  hostPath:
    path: "/mnt/efs/shared_fs/mlde_shared"
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: pdk-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 200Gi
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
  capacity:
    storage: 200Gi
  accessModes:
    - ReadWriteMany
  hostPath:
    path: "/mnt/efs/shared_fs/mlde_shared"
---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: pdk-pvc
  namespace: gpu-pool
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 200Gi
EOF
```

You can validate that necessary components were created (and successfuly bound together) with the following commands:
```bash
kubectl get sc

kubectl get pv

kubectl get pvc

kubectl -n gpu-pool get pvc
```



Create the gpu-pool namespace

```bash
kubectl create ns gpu-pool
```


&nbsp;
<a name="step9">
### Step 9 - Create configuration .yaml file for MLDM and MLDE
</a>

This command will create a .yaml file that you can review in a text editor.

```bash
cat <<EOF > helm_values.yaml
deployTarget: "MINIO"
pachd:
  enabled: true
  externalService:
    enabled: true
  storage:
    backend: MINIO
    minio:
      bucket: "mldm-bucket"
      endpoint: "minio.default.svc.cluster.local:9000"
      id: "minioadmin"
      secret: "minioadmin"
      secure: "false"
etcd:
  size: 10Gi
loki-stack:
  loki:
    securityContext:
      fsGroup: 0
      runAsGroup: 0
      runAsNonRoot: false
      runAsUser: 0
    persistence:
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

determined:
  enabled: true
  detVersion: "0.28.1"
  imageRegistry: determinedai
  enterpriseEdition: false
  imagePullSecretName:
  createNonNamespacedObjects: true
  masterPort: 8080
  useNodePortForMaster: false
  defaultPassword: ${ADMIN_PASSWORD}
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
    type: s3
    bucket: mlde-bucket
    accessKey: minioadmin
    secretKey: minioadmin
    endpointUrl: http://minio.default.svc.cluster.local:9000
  maxSlotsPerPod: 4
  masterCpuRequest: "4"
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
  defaultAuxResourcePool: default
  defaultComputeResourcePool: gpu-pool
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
                  claimName: pdk-pvc
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
                  claimName: pdk-pvc
            tolerations:
              - key: "nvidia.com/gpu"
                operator: "Equal"
                value: "present"
                effect: "NoSchedule"
EOF
```


&nbsp;
<a name="step10">
### Step 10 - Install MLDM and MLDE using Helm
</a>

First, download the helm chart:

```bash
helm repo add pachyderm https://helm.pachyderm.com

helm repo update
```

Then run the installer, referencing the .yaml file you just created:

```bash
helm install pachyderm -f ./helm_values.yaml pachyderm/pachyderm --namespace default
```

Give it a couple of minutes for all the services to be up and running. You can run `kubectl get pods` to see if any pods failed or are stuck. Wait until all pods are running before continuing.


&nbsp;
<a name="step11">
### Step 11 - Retrieve MLDM and MLDE IP addresses and configure command line clients
</a>

In this step, we'll configure the `pachctl` and `det` clients. This will be important later, as we create the project, repo and pipeline for the PDK environment.

```bash
export MLDM_HOST=$(kubectl get svc pachyderm-proxy --output jsonpath='{.status.loadBalancer.ingress[0].ip}')

export MLDM_URL="http://${MLDM_HOST}:80"

echo $MLDM_URL

pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}
```
PS: Depending on how your load balancer is setup, you may need to use `hostname` instead of `ip` to get the service address.

PS: You need a working URL to continue. Depending on how your cluster's networking is setup, you might need to run port forwarding in order to access the service.

At this time, the MLDM UI will be accessible:


![alt text][k8s_mldm_01_dashboard]

[k8s_mldm_01_dashboard]: images/k8s_mldm_01_dashboard.png "MLDM Dashboard"

A new capabiity of MLDM 2.8.1 is **Cluster Defaults**, which allows admins to set configurations that will be automatically applied to all pipelines (unless explicitly overwritten by the pipeline definition). Click the **Cluster Defaults** button and replace the existing configuration with the following:

```json
{
  "createPipelineRequest": {
    "resourceRequests": {
      "cpu": 1,
      "memory": "256Mi",
      "disk": "1Gi"
    },
    "datumTries" : 1,
    "parallelismSpec": {"constant": 1},
    "autoscaling" : true,
    "sidecarResourceRequests": {
      "cpu": 1,
      "memory": "256Mi",
      "disk": "1Gi"
    }
  }
}
```

The configuration changes we are applying will:
- Disable retries in case of failed jobs (`datumTries: 1`)
- Run each pipeline in a single pod (`parallelismSpec - constant: 1`)
- Automatically delete the pod once the pipeline is completed to release the CPU (`autoscaling: true`)

Do keep in mind that these settings are not recommended for all environments, especially Production.

Click **Continue** and **Save** to apply the changes.

&nbsp;

Similar to the steps taken for MLDM, save the static IP for MLDE in an environment variable:


```bash
export MLDE_HOST=$(kubectl get svc determined-master-service-determinedai --output jsonpath='{.status.loadBalancer.ingress[0].ip}')

export MLDE_URL="http://${MLDE_HOST}:8080"

echo $MLDE_URL

export DET_MASTER=${MLDE_HOST}:8080

echo ${ADMIN_PASSWORD}

det u login admin
```
(leave the password empty and press enter to login as admin)

PS: As with MLDM, you may need to use port forwarding, depending on how your cluster's network is setup.

Once logged in, you can run `det e list`, which should return an empty list. If you get an error message, check the MLDE pod and service for errors.

You should also be able to access the MLDE UI. Login as user **admin** (leave password field empty). Once logged in, check the **Cluster** page and make sure the GPU resources are showing up:


![alt text][k8s_mlde_01_ui]

[k8s_mlde_01_ui]: images/k8s_mlde_01_ui.png "MLDE UI - Clusters"




&nbsp;
<a name="step12">
### Step 12 - (Optional) Test Components
</a>

In this optional step, we can test MLDM (by creating a pipeline) and MLDE (by creating an experiment)

To test MLDM, run the following commands. They will create a new project, repo and pipeline, which will run for a few images we'll download.

```bash
mkdir opencv

cd opencv

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

cd ..
```

&nbsp;

At this time, you should see the OpenCV project and pipeline in the MLDM UI:


![alt text][k8s_mldm_02_test_pipeline]

[k8s_mldm_02_test_pipeline]: images/k8s_mldm_02_test_pipeline.png "MLDM Test Pipeline"


&nbsp;

You should also be able to see the *chunks* in MinIO. This confirms that MLDM is able to write to the storage bucket.


![alt text][k8s_minio_03_chunks]

[k8s_minio_03_chunks]: images/k8s_minio_03_chunks.png "MLDM Storage Bucket"


PS: Do not modify or delete chunks, as it will break integrity.


&nbsp;

To test MLDE, you'll need to download the examples from the public github:

```bash

mkdir mlde_exp

cd mlde_exp

git clone https://github.com/determined-ai/determined.git .

```
&nbsp;
Once the command completes, run this command to modify the `./examples/computer_vision/iris_tf_keras/const.yaml` file that will be used to run the experiment:

```bash
cat <<EOF > ./examples/computer_vision/iris_tf_keras/const.yaml
name: iris_tf_keras_const
data:
  train_url: http://download.tensorflow.org/data/iris_training.csv
  test_url: http://download.tensorflow.org/data/iris_test.csv
hyperparameters:
  learning_rate: 1.0e-4
  learning_rate_decay: 1.0e-6
  layer1_dense_size: 16
  global_batch_size: 16
searcher:
  name: single
  metric: val_categorical_accuracy
  smaller_is_better: false
  max_length:
    batches: 500
entrypoint: model_def:IrisTrial
EOF
```

The changes we're making will reduce the global batch size and max batch lenght, to speed up training.

Then run this command to create the experiment:

```bash
det experiment create -f ./examples/computer_vision/iris_tf_keras/const.yaml ./examples/computer_vision/iris_tf_keras

cd ..
```
 If this command fails, make sure the `DET_MASTER` environment variable is set. Keep in mind that the client can timeout while it's waiting for the experiment image to be pulled. It does not mean the experiment has failed; you can still check the UI or use `det e list` to see the current status of this experiment.


&nbsp;

Your experiment will appear under Uncategorized (we will change that for the PDK experiments). You can track the Experiment log to see if there are any issues.


![alt text][k8s_mlde_04_test_experiment]

[k8s_mlde_04_test_experiment]: images/k8s_mlde_04_test_experiment.png "MLDE Experiment"


&nbsp;

You can also check the MLDE files in the MinIO UI, to see the checkpoints that were saved:


![alt text][k8s_mlde_05_storage]

[k8s_mlde_05_storage]: images/k8s_mlde_05_storage.png "MLDE Storage Bucket"

This confirms that MLDE is able to access the storage bucket as well.


&nbsp;

Finally, go to the MLDE **Home Page** and click the **Launch JupyterLab** button. In the configuration pop-up, select the *Uncategorized* workspace, set the *Resource Pool* to **gpu-pool** (this is important, because the *default* pool has no GPUs available) and set the number of *Slots* (GPUs) to 1. Or set the number of slots to 0 and select the *default* Resource Pool to create a CPU-based notebook environment.

Click **Launch** to start the JupyterLab environment.

The first run should take about one minute to pull and run the image.


![alt text][aws_mlde_06_jupyter]

[aws_mlde_06_jupyter]: images/aws_mlde_06_jupyter.png "MLDE Launch JupyterLab"


In the new tab, make sure the *shared_fs* folder is listed. In this folder, users will be able to permanently store their model assets, notebooks and other files.

![alt text][aws_mlde_07_shared_folder]

[aws_mlde_07_shared_folder]: images/aws_mlde_07_shared_folder.png "MLDE Notebook Shared Folder"

PS: If the JupyterLab environment fails to load, it might be because of an issue with the shared folder. Run `kubectl -n gpu-pool describe pod` against the new pod to see why the pod failed to run.



&nbsp;
<a name="step13">
### Step 13 - Prepare for PDK Setup
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
    model:
      modelFormat:
        name: sklearn
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
curl -v \
-H "Content-Type: application/json" \
-H "Host: ${SERVICE_HOSTNAME}" \
http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/sklearn-iris:predict \
-d @./iris-input.json
```

What we're looking for in the ouput is a status code of 200 (success) and a JSON payload with a list of values:


![alt text][k8s_kserve_02_prediction]

[k8s_kserve_02_prediction]: images/k8s_kserve_02_prediction.png "KServe Sample Prediction"



Make sure you get a valid response before continuing, as the deployment will fail if KServer is not properly setup.

The last part of this step is basically some housekeeping tasks to set the stage for the PDK flow.

First, we create a secret that will store variables that will be used by both MLDM pipelines and MLDE experiments. In this case, we'll use internal hostnames, as all these components are running in the same cluster:

```bash
export MLDE_SVC=determined-master-service-pachyderm.default.svc.cluster.local
export MLDM_SVC=pachyderm-proxy.default.svc.cluster.local

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
kubectl apply -f pipeline-secret.yaml
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
  namespace: default
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
    serving.kserve.io/s3-endpoint: pachd.default:30600
    serving.kserve.io/s3-usehttps: "0"
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "blahblahblah"
  AWS_SECRET_ACCESS_KEY: "blahblahblah"
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pach-deploy
  namespace: ${KSERVE_MODELS_NAMESPACE}
  annotations:
    serving.kserve.io/s3-endpoint: pachd.default:30600
    serving.kserve.io/s3-usehttps: "0"
secrets:
- name: pach-kserve-creds
EOF
```


&nbsp;
<a name="step14">
### Step 14 - [Optional] Configure KServe UI
</a>

The quick installer we used for KServe does not include a UI to see the deployments. We can optionally deploy one, using the instructions described in this step.

We'll deploy the UI to the same namespace that is used to deploy the models (`${KSERVE_MODELS_NAMESPACE}`)

First, we need to create the necessary roles, service accounts, etc. Run this command to setup the necessary permissions:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: models-webapp-sa
  namespace: ${KSERVE_MODELS_NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: models-webapp-limited
  namespace: ${KSERVE_MODELS_NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: models-controller
rules:
- apiGroups: ["*"]
  resources: ["namespaces"]
  verbs: ["get", "watch", "list"]
- apiGroups: ["serving.kserve.io"]
  resources: ["*"]
  verbs: ["*"]
- apiGroups: ["serving.knative.dev"]
  resources: ["*"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: namespace-viewer
rules:
- apiGroups: ["*"]
  resources: ["namespaces"]
  verbs: ["get", "watch", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: models-viewer
  namespace: ${KSERVE_MODELS_NAMESPACE}
rules:
- apiGroups: ["serving.kserve.io", "serving.knative.dev"]
  resources: ["*"]
  verbs: ["get", "watch", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: control-models
subjects:
- kind: ServiceAccount
  name: models-webapp-sa
  namespace: ${KSERVE_MODELS_NAMESPACE}
roleRef:
  kind: ClusterRole
  name: models-controller
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: view-models
  namespace: ${KSERVE_MODELS_NAMESPACE}
subjects:
- kind: ServiceAccount
  name: models-webapp-limited
  namespace: ${KSERVE_MODELS_NAMESPACE}
roleRef:
  kind: Role
  name: models-viewer
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: view-namespaces
  namespace: ${KSERVE_MODELS_NAMESPACE}
subjects:
- kind: ServiceAccount
  name: models-webapp-limited
  namespace: ${KSERVE_MODELS_NAMESPACE}
roleRef:
  kind: ClusterRole
  name: namespace-viewer
  apiGroup: rbac.authorization.k8s.io
EOF
```

Next, create the deployment and the service using this command:

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: models-webapp
  namespace: ${KSERVE_MODELS_NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: models-webapp
  template:
    metadata:
      labels:
        app: models-webapp
    spec:
      serviceAccountName: models-webapp-sa
      containers:
      - name: models-webapp
        image: us-central1-docker.pkg.dev/dai-dev-554/pdk-registry/pdk_kserve_webapp:1.0
        env:
        - name: APP_SECURE_COOKIES
          value: "False"
        - name: APP_DISABLE_AUTH
          value: "True"
        - name: APP_PREFIX
          value: "/"
        command: ["gunicorn"]
        args:
        - -w
        - "3"
        - --bind
        - "0.0.0.0:8081"
        - "--access-logfile"
        - "-"
        - "entrypoint:app"
        resources:
          limits:
            memory: "1Gi"
            cpu: "500m"
        ports:
        - containerPort: 8081
---
apiVersion: v1
kind: Service
metadata:
  name: model-webapp-service
  namespace: ${KSERVE_MODELS_NAMESPACE}
  labels:
    app: kserve-webapp
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  selector:
    app: models-webapp
  ports:
  - port: 8081
    targetPort: 8081
EOF
```

PS: If you would like to build your own image, this Github page contains the source:<br/>
https://github.com/kserve/models-web-app/tree/master

Next, get the URL for the KServe UI:

```bash
export KSERVE_UI_HOST=$(kubectl -n ${KSERVE_MODELS_NAMESPACE} get svc model-webapp-service --output jsonpath='{.status.loadBalancer.ingress[0].ip}')

export KSERVE_UI_URL="http://${KSERVE_UI_HOST}:8081"

echo $KSERVE_UI_URL
```

You can access the URL to see the deployed model (make sure to select the correct namespace).


![alt text][k8s_kserve_03_ui]

[k8s_kserve_03_ui]: images/k8s_kserve_03_ui.png "KServe UI"






&nbsp;
<a name="step15">
### Step 15 - [Optional] Prepare Docker and the Registry to manage images
</a>

The samples provided here already contain images you can use for training and deployment. This step is only necessary if you want to build your own images. In this case, you will find the Dockerfiles for each example in this repository.

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
  mldm_bucket_name: "mldm-bucket"
  mldm_host: "${MLDM_SVC}"
  mldm_port: "9090"
  mldm_url: "${MLDM_URL}"
  mldm_pipeline_secret: "pipeline-secret"
  mlde_bucket_name: "mlde-bucket"
  mlde_host: "${MLDE_SVC}"
  mlde_port: "8080"
  mlde_url: "${MLDE_URL}"
  minio_url: "http://minio.default.svc.cluster.local:9000"
  kserve_ui_url: "${KSERVE_UI_URL}"
  kserve_model_bucket_name: "kserve-bucket"
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
ubuntu@ip-100-64-13-46:~$ kubectl exec -i -t dnsutils -- nslookup pg-bouncer.default.svc.cluster.local
Server:		10.152.183.10
Address:	10.152.183.10#53

Name:	pg-bouncer.default.svc.cluster.local
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
kubectl port-forward svc/pachyderm-proxy 9090:9090

```

You will then be able to access these services through a `http://localhost:<port>` URL.




&nbsp;

---

&nbsp;

The installation steps are now completed. At this time, you have a working cluster, with MLDM, MLDE and KServe deployed.

Next, return to [the main page](README.md) to go through the steps to prepare and deploy the PDK flow for the dogs-and-cats demo.

<br/><br/>
