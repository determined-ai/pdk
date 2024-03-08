![alt text][hpe_logo]

[hpe_logo]: images/hpe_logo.png "HPE Logo"

# PDK - Pachyderm | Determined | KServe
## Deployment Guide for Google Cloud
<b>Date/Revision:</b> February 23, 2024

This guide will walk you through the steps of deploying the PDK components to Google Cloud.

## Reference Architecture
The installation will be performed on the following hardware:

- 3x e2-standard-16 CPU-based nodes (16 vCPUs, 64GB RAM, 1000GB SSD)
- 2x n1-standard-8 GPU-based nodes (4 NVIDIA-T4, 16 vCPUs, 64GB RAM, 1000GB SSD)

The 3 CPU-based nodes will be used to run the services for all 3 products, and the MLDM pipelines. The GPU-based nodes will be used to run MLDE experiments.

The following software versions will be used for this installation:

- Python: 3.8 and 3.9
- Kubernetes (K8s): latest supported *(currently 1.27)*
- Postgres: 13
- MLDE (Determined.AI): latest *(currently 0.28.1)*
- MLDM (Pachyderm): latest *(currently 2.8.4)*
- KServe: 0.12.0-rc0 (Quickstart Environment)

PS: some of the commands used here are sensitive to the version of the product(s) listed above.


## Prerequisites
To follow this documentation you will need:

- The following applications, installed and configured in your computer:
  - kubectl
  - docker (you'll need docker desktop or similar to create and push images)
  - git (to clone the repository with the examples)
  - gcloud (make sure it's initialized and logged in; basic client configuration is out of scope for this doc)
  - helm
  - jq
  - openssl (to generate a random password for the MLDE admin)  
  - patchctl (the MLDM command line client)
  - det (the MLDE command line client)
- Access to a Google Cloud account
- A Project in Google Cloud, where your user has the following roles:
  - Cloud SQL Admin
  - Compute Network Admin
  - Kubernetes Engine Admin
  - Policy Tag Admin
  - Project IAM Admin
  - Role Administrator
  - Storage Admin
  - Artifact Registry Administrator
  - A Custom role, with the following assigned permissions:
    - iam.serviceAccounts.actAs
    - iam.serviceAccounts.create
    - iam.serviceAccounts.delete
    - iam.serviceAccounts.disable
    - iam.serviceAccounts.enable
    - iam.serviceAccounts.get
    - iam.serviceAccounts.getIamPolicy
    - iam.serviceAccounts.setIamPolicy

&nbsp;

The lack of these permissions will cause some commands to fail. Check your permissions if you run into any issues.

&nbsp;

--------

## Installing the Cluster

In this section, we will execute the following steps:

[01 - Set Environment Variables](#step1)

[02 - Test the pre-req applications and configure the gcloud client](#step2)

[03 - Create the main service account and custom role](#step3)

[04 - Create the GKE cluster](#step4)

[05 - Create the GPU node pool in the cluster](#step5)

[06 - Create Storage buckets](#step6)

[07 - Create Postgres Database](#step7)

[08 - Create static IP for MLDM](#step8)

[09 - Configure security settings for MLDM - Loki](#step9)

[10 - Configure security settings for the MLDE GPU Node Pool](#step10)

[11 - Deploy KServe](#step11)

[12 - Create static IP for MLDE](#step12)

[13 - Deploy nginx, configured to use the static IP](#step13)

[14 - Prepare MLDE installation assets](#step14)

[15 - Create configuration .yaml file for MLDM and MLDE](#step15)

[16 - Install MLDM and MLDE using Helm](#step16)

[17 - Create new Ingress for MLDE](#step17)

[18 - Retrieve MLDM and MLDE IP addresses and configure command line clients](#step18)

[19 - (Optional) Test Components](#step19)

[20 - Prepare for PDK Setup](#step20)

[21 - [Optional] Configure KServe UI](#step21)

[22 - [Optional] Prepare Docker and the Container Registry](#step22)

[23 - Save data to Config Map](#step23)

[24 - Create Cleanup Script](#step24)


There is also a list of GCP-specific [Useful Commands](#commands) at the bottom of the page.


#### <b>IMPORTANT: These steps were created and tested on an M1 MacOS computer. Some of the commands might work differently (or not at all) in other operating systems. Check the command documentation for an alternative syntax, if you are using a different OS.</b>

#### NOTE: It's recommended to run these instructions one at a time, so you can diagnose in case of issues. The syntax for some of the commands documented here might become invalid, as new versions of these applications are released.



&nbsp;
<a name="step1">
### Step 1 - Set Environment Variables
</a>

You should only need to change the first block of variables.

All commands listed throghout this document must be executed in the same terminal window.

PS: Keep in mind that custom roles in Google Cloud will take 7 days to be deleted, and they cannot be named after an existing role, even if that role is deleted. Effectively, you cannot reuse the same role name for 7 days after deleting it. Because of that, we are adding a dynamic suffix to the GSA_ROLE_NAME variable. That way, you can reinstall the cluster immediately without running into errors when creating the role.

```bash
# MODIFY THESE VARIABLES
export PROJECT_ID="your-google-cloud-project-id"
export NAME="your-name-pdk"
# Role names cannot have spaces, special characters or dashes.
export GSA_ROLE="your_gsa_role_name"

# Create dynamic appendix for role name
export ROLE_SUFFIX=$(openssl rand -base64 12 | tr -dc A-Za-z0-9 | head -c5)
export GSA_ROLE_NAME="${GSA_ROLE}_${ROLE_SUFFIX}"


# These can be modified as needed
export GCP_REGION="us-central1"
export GCP_ZONE="us-central1-c"
export K8S_VERSION="1.27.3-gke.100"
export KSERVE_MODELS_NAMESPACE="models"
export CLUSTER_MACHINE_TYPE="e2-standard-16"
export GPU_MACHINE_TYPE="n1-standard-16"
export SQL_CPU="2"
export SQL_MEM="7680MB"

# You should not need to modify any of these variables
export CLUSTER_NAME="${NAME}-cluster"
export MLDM_BUCKET_NAME="${NAME}-repo-mldm"
export MLDE_BUCKET_NAME="${NAME}-repo-mlde"
export LOKI_BUCKET_NAME="${NAME}-logs-gcs"
export MODEL_ASSETS_BUCKET_NAME="${NAME}-repo-models"
export CLOUDSQL_INSTANCE_NAME="${NAME}-sql"
export GSA_NAME="${NAME}-gsa"
export LOKI_GSA_NAME="${NAME}-loki-gsa"
export STATIC_IP_NAME="${NAME}-ip"
export MLDE_STATIC_IP_NAME="${NAME}-mlde-ip"
export KSERVE_STATIC_IP_NAME="${NAME}-kserve-ip"

export ROLE1="roles/cloudsql.client"
export ROLE2="roles/storage.admin"
export ROLE3="roles/storage.objectCreator"
export ROLE4="roles/container.admin"
export ROLE5="roles/containerregistry.ServiceAgent"

export SERVICE_ACCOUNT="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export LOKI_SERVICE_ACCOUNT="${LOKI_GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export PACH_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[default/pachyderm]"
export SIDECAR_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[default/pachyderm-worker]"
export CLOUDSQLAUTHPROXY_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[default/k8s-cloudsql-auth-proxy]"
export MLDE_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[default/determined-master-determinedai]"
export MLDE_DF_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[default/default]"
export MLDE_GPU_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[gpu-pool/default]"
export MLDE_KS_WI="serviceAccount:${PROJECT_ID}.svc.id.goog[${KSERVE_MODELS_NAMESPACE}/default]"

# Generate admin password for MLDE (or set your own password)
export ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -dc A-Za-z0-9 | head -c16)

# Optionally, set a different password for the database:
export SQL_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
```



&nbsp;
<a name="step2">
### Step 2 - Test the pre-req applications and configure the gcloud client
</a>

Make sure all these commands return successfully. If one of them fails, fix the issue before continuing.

```bash
kubectl version --client=true
gcloud version
helm version
pachctl version
det version
jq --version

gcloud config set project ${PROJECT_ID}
gcloud config set compute/zone ${GCP_ZONE}
gcloud config set container/cluster ${CLUSTER_NAME}
gcloud services enable container.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable artifactregistry.googleapis.com
```



&nbsp;
<a name="step3">
### Step 3 - Create the main service account and custom role
</a>

In this step, we create the Service Account and custom role that will be used by the different services.

```bash
gcloud iam service-accounts create ${GSA_NAME}

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="${ROLE1}"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="${ROLE2}"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="${ROLE3}"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="${ROLE4}"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="${ROLE5}"

gcloud iam roles create ${GSA_ROLE_NAME} \
  --project=${PROJECT_ID} \
  --title=${GSA_ROLE_NAME} \
  --description="Additional permissions" \
  --stage GA \
  --permissions=storage.multipartUploads.abort,storage.multipartUploads.create,storage.multipartUploads.list,storage.multipartUploads.listParts,storage.objects.create,storage.objects.delete,storage.objects.get,storage.objects.getIamPolicy,storage.objects.list,storage.objects.update,iam.serviceAccounts.getIamPolicy,iam.serviceAccounts.setIamPolicy,iam.serviceAccounts.getAccessToken

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
 --member="serviceAccount:${SERVICE_ACCOUNT}" \
 --role="projects/${PROJECT_ID}/roles/${GSA_ROLE_NAME}"
```

PS: the list of permissions in the create role command must be in a single line. Careful when copying and pasting.

Also, the create role command may return a warning message saying 'API is not enabled for permissions'. This message can be safely ignored.



&nbsp;
<a name="step4">
### Step 4 - Create the GKE cluster
</a>

This command will create the cluster with the CPU node pool.

```bash
gcloud container clusters create ${CLUSTER_NAME} \
 	--project ${PROJECT_ID} \
 	--zone ${GCP_ZONE} \
 	--cluster-version ${K8S_VERSION} \
 	--release-channel "None" \
 	--machine-type ${CLUSTER_MACHINE_TYPE} \
 	--image-type "COS_CONTAINERD" \
 	--disk-type="pd-ssd" \
  --disk-size "1000" \
 	--metadata disable-legacy-endpoints=true \
 	--service-account ${SERVICE_ACCOUNT} \
 	--num-nodes "3" \
 	--logging=SYSTEM,WORKLOAD \
 	--monitoring=SYSTEM \
 	--enable-ip-alias \
 	--network "projects/${PROJECT_ID}/global/networks/default" \
 	--subnetwork "projects/${PROJECT_ID}/regions/us-central1/subnetworks/default" \
 	--no-enable-intra-node-visibility \
 	--default-max-pods-per-node "220" \
 	--enable-autoscaling \
 	--min-nodes "3" \
 	--max-nodes "6" \
 	--location-policy "BALANCED" \
 	--security-posture=standard \
 	--workload-vulnerability-scanning=disabled \
  --enable-master-authorized-networks \
  --master-authorized-networks 0.0.0.0/0 \
 	--addons HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver,GcpFilestoreCsiDriver \
 	--no-enable-autoupgrade \
 	--enable-autorepair \
 	--max-surge-upgrade 1 \
 	--max-unavailable-upgrade 0 \
 	--enable-shielded-nodes \
  --enable-dataplane-v2 \
 	--workload-pool=${PROJECT_ID}.svc.id.goog \
 	--workload-metadata="GKE_METADATA" \
 	--node-locations ${GCP_ZONE} \
  --tags pdk
```

This process will take several minutes. The output  message will show the cluster configuration. You can also check the status of the provisioning in the Google Cloud Console.


&nbsp;
<a name="step5">
### Step 5 - Create the GPU node pool in the cluster
</a>

The configuration used here will provision 4 GPUs per node. You can change it to count=2 or count=1, as needed.

```bash
gcloud container node-pools create "gpu-pool" \
	--project ${PROJECT_ID} \
	--cluster ${CLUSTER_NAME} \
	--zone ${GCP_ZONE} \
	--node-version ${K8S_VERSION} \
	--machine-type ${GPU_MACHINE_TYPE} \
	--accelerator type=nvidia-tesla-t4,count=4 \
	--image-type "COS_CONTAINERD" \
	--disk-type="pd-ssd" \
  --disk-size "1000" \
	--node-labels nodegroup-role=gpu-worker \
	--metadata disable-legacy-endpoints=true \
  --node-taints nvidia.com/gpu=present:NoSchedule \
	--num-nodes "1" \
	--enable-autoscaling \
	--min-nodes "1" \
	--max-nodes "4" \
	--location-policy "BALANCED" \
	--enable-autoupgrade \
	--enable-autorepair \
	--max-surge-upgrade 1 \
	--max-unavailable-upgrade 0 \
  --scopes=storage-full,cloud-platform \
	--node-locations ${GCP_ZONE} \
  --tags pdk
```

This can take several minutes to complete. If it takes more than 1 hour, it will timeout the client. If that happens, track the progress of the provisioning process through the Google Cloud web console.


Once the GPU node pool is provisioned, all nodes should show up as ready in the console:

![alt text][gcp_cluster_01_status]

[gcp_cluster_01_status]: images/gcp_cluster_01_status.png "GKE Cluster nodes"



After the cluster is created, configure your kubectl context:

```bash
gcloud container clusters get-credentials ${CLUSTER_NAME}
```

At this point, you should be able to run `kubectl get nodes` to see the list of 5 nodes. Make sure this is working before continuing.

Depending on your environment, you might need to grant additional permissions to your kubernetes user. Run this command to make sure you won't run into permissions errors:

```bash
kubectl create clusterrolebinding cluster-admin-binding --clusterrole=cluster-admin --user=$(gcloud config get-value account)
```



&nbsp;
<a name="step6">
### Step 6 - Create Storage buckets
</a>

We'll create 4 storage buckets: 1 for MLDE, 2 for MLDM and 1 to store models for KServe.

```bash
gsutil mb -l ${GCP_REGION} gs://${MLDM_BUCKET_NAME}

gsutil mb -l ${GCP_REGION} gs://${LOKI_BUCKET_NAME}

gsutil mb -l ${GCP_REGION} gs://${MLDE_BUCKET_NAME}

gsutil mb -l ${GCP_REGION} gs://${MODEL_ASSETS_BUCKET_NAME}
```



&nbsp;
<a name="step7">
### Step 7 - Create Postgres Database
</a>

Use this command to provision a cloud Postgres database:

```bash
gcloud sql instances create ${CLOUDSQL_INSTANCE_NAME} \
  --database-version=POSTGRES_13 \
  --cpu=${SQL_CPU} \
  --memory=${SQL_MEM} \
  --zone=${GCP_ZONE} \
  --availability-type=ZONAL \
  --storage-size=50GB \
  --storage-type=SSD \
  --storage-auto-increase \
  --root-password=${SQL_ADMIN_PASSWORD}
```

PS: If you want to use Postgres 14, additional configuration steps will be needed, because the default password encryption was changed between versions. Make sure to check the documentation for additional steps.

Once the instance is available, create the databases for MLDM and MLDE:

```bash
gcloud sql databases create pachyderm -i "${CLOUDSQL_INSTANCE_NAME}"

gcloud sql databases create dex -i "${CLOUDSQL_INSTANCE_NAME}"

gcloud sql databases create determined -i "${CLOUDSQL_INSTANCE_NAME}"
```

Finally, save the database connection string to an environment variable:

```bash
export CLOUDSQL_CONNECTION_NAME=$(gcloud sql instances describe ${CLOUDSQL_INSTANCE_NAME} --format=json | jq ."connectionName")

echo $CLOUDSQL_CONNECTION_NAME
```



&nbsp;
<a name="step8">
### Step 8 - Create static IP for MLDM
</a>

Create a static IP to be used by MLDM and save it to an environment variable.

```bash
gcloud compute addresses create ${STATIC_IP_NAME} --region=${GCP_REGION}

export STATIC_IP_ADDR=$(gcloud compute addresses describe ${STATIC_IP_NAME} --region=${GCP_REGION} --format=json --flatten=address | jq '.[]' )

echo $STATIC_IP_ADDR
```



&nbsp;
<a name="step9">
### Step 9 - Configure security settings for MLDM - Loki
</a>

In this step, we create a service account for the MLDM - Loki service.
Also, we'll bind some MLDE and MLDM services to the main service account (so they can access the DB and the storage bucket).


```bash
gcloud iam service-accounts create ${LOKI_GSA_NAME}

gcloud iam service-accounts keys create "${LOKI_GSA_NAME}-key.json" --iam-account="$LOKI_SERVICE_ACCOUNT"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${LOKI_SERVICE_ACCOUNT}" \
    --role="${ROLE2}"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${LOKI_SERVICE_ACCOUNT}" \
    --role="${ROLE3}"

kubectl -n default create secret generic loki-service-account --from-file="${LOKI_GSA_NAME}-key.json"

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${PACH_WI}"

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${SIDECAR_WI}"

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${CLOUDSQLAUTHPROXY_WI}"

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${MLDE_WI}"

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${MLDE_DF_WI}"
```



&nbsp;
<a name="step10">
### Step 10 - Configure security settings for the MLDE GPU Node Pool
</a>

First, we need to deploy the GPU daemonset. Without it, your nodes will show 0 allocatable GPUs:

```bash
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/container-engine-accelerators/master/nvidia-driver-installer/cos/daemonset-preloaded.yaml
```

This will take a couple of minutes to take effect. Run a `kubectl get nodes` and then a `kubectl describe node <node_name>` in one of the GPU nodes. Look for the Allocatable section; if you don't see a `nvidia.com/gpu: 4` entry in that list, wait a few seconds and check again. Do not continue until the GPUs are being listed as allocatable.

You can also use this command to list allocatable GPUs per node:

```bash
kubectl describe nodes  |  tr -d '\000' | sed -n -e '/^Name/,/Roles/p' -e '/^Capacity/,/Allocatable/p' -e '/^Allocated resources/,/Events/p'  | grep -e Name  -e  nvidia.com  | perl -pe 's/\n//'  |  perl -pe 's/Name:/\n/g' | sed 's/nvidia.com\/gpu:\?//g'  | sed '1s/^/Node Available(GPUs)  Used(GPUs)/' | sed 's/$/ 0 0 0/'  | awk '{print $1, $2, $3}'  | column -t
```

For the MLDE setup, we'll configure the GPU nodes to be in a separate Resource Pool. This requires a new namespace for the GPU nodes, as experiments will run as pods in that namespace (that will then be bound to the GPU nodes). We will need to grant permissions for the service accounts in both *default* and *gpu-pool* namespaces, so experiments, notebooks and other tasks can save and read checkpoint files from the storage bucket. The service account for MLDE is created by the installer, so we will set those permissions once MLDE is deployed. For now, run these commands to grant bucket access permissions:

```bash
kubectl create ns gpu-pool

kubectl annotate serviceaccount default \
  -n default \
  iam.gke.io/gcp-service-account=${SERVICE_ACCOUNT}

kubectl annotate serviceaccount default \
  -n gpu-pool \
  iam.gke.io/gcp-service-account=${SERVICE_ACCOUNT}

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${MLDE_GPU_WI}"
```



&nbsp;
<a name="step11">
### Step 11 - Deploy KServe
</a>

KServe is a standard Model Inference Platform on Kubernetes, built for highly scalable use cases. It provides performant, standardized inference protocol across ML frameworks, including PyTorch, TensorFlow and Keras.
Additionally, KServe provides features such as automatic scaling, monitoring, and logging, making it easy to manage deployed models in production. Advanced features, such as canary rollouts, experiments, ensembles and transformers are also available.
For more information on KServe, please visit <a href="https://kserve.github.io/website/0.9/">the official KServe documentation</a>.


Installation of KServe is very straightforward, because we are using the Quick Start. This is naturally only an option for test or demo environments;

```bash
curl -s "https://raw.githubusercontent.com/kserve/kserve/master/hack/quick_install.sh" | bash
```

After running this command, wait about 10 minutes for all the services to be properly initialized.



&nbsp;
<a name="step12">
### Step 12 - Create static IP for MLDE
</a>

```bash
gcloud compute addresses create ${MLDE_STATIC_IP_NAME} --region=${GCP_REGION}

export MLDE_STATIC_IP_ADDR=$(gcloud compute addresses describe ${MLDE_STATIC_IP_NAME} --region=${GCP_REGION} --format=json --flatten=address | jq '.[]' )

echo $MLDE_STATIC_IP_ADDR
```



&nbsp;
<a name="step13">
### Step 13 - Deploy nginx, configured to use the static IP
</a>

Nginx will be configured to listen on port 80 (instead of the default 8080 used by MLDE).

```bash

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

helm repo update

helm upgrade --install -n ingress-system --create-namespace ingress-nginx ingress-nginx/ingress-nginx \
  --set controller.service.loadBalancerIP=${MLDE_STATIC_IP_ADDR}

```

PS: This could take a couple of minutes. Make sure to run `kubectl -n ingress-system get svc` and make sure that the External IP column matches the static IP that was provisioned. If the field is empty (or showing Pending), investigate and fix it before continuing.

Make sure the Public IP matches the static IP you've created in the previous step:

![alt text][gcp_mlde_01_nginx]

[gcp_mlde_01_nginx]: images/gcp_mlde_01_nginx.png "Ingress IP configuration"



&nbsp;
<a name="step14">
### Step 14 - Prepare MLDE installation assets
</a>

First, we need to provision shared storage for MLDE. This will be used to provide a shared folder that can be used by Notebook users in the MLDE UI. This will allow users to save their own code and notebooks in a persistent volume.

For this exercise, we will create a 200GB disk. You can increase this capacity as needed.

First, create the disk:

```bash
gcloud compute disks create --size=200GB --zone=${GCP_ZONE} ${NAME}-pdk-nfs-disk
```

Next, we'll create a NFS server that uses this disk:

```bash
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nfs-server
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      role: nfs-server
  template:
    metadata:
      labels:
        role: nfs-server
    spec:
      containers:
      - name: nfs-server
        image: gcr.io/google_containers/volume-nfs:0.8
        ports:
          - name: nfs
            containerPort: 2049
          - name: mountd
            containerPort: 20048
          - name: rpcbind
            containerPort: 111
        securityContext:
          privileged: true
        volumeMounts:
          - mountPath: /exports
            name: mypvc
      volumes:
        - name: mypvc
          gcePersistentDisk:
            pdName: ${NAME}-pdk-nfs-disk
            fsType: ext4
EOF
```

Next, create a Service to expose the disk:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: nfs-server
spec:
  ports:
    - name: nfs
      port: 2049
    - name: mountd
      port: 20048
    - name: rpcbind
      port: 111
  selector:
    role: nfs-server
EOF
```

Because Persistent Volume Claims are namespace-bound objects, and we'll have 2 namespaces (*default*, where CPU jobs will run, and *gpu-pool*, there GPU jobs will run), we'll need two Persistent Volume Claims, tied to 2 Persistent Volumes. We'll create the PVs as *ReadWriteMany* to ensure concurrent access by the different PVCs.

Run this command to create the PV and PVC for the *default* namespace:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs
spec:
  capacity:
    storage: 200Gi
  accessModes:
    - ReadWriteMany
  nfs:
    server: nfs-server.default.svc.cluster.local
    path: "/"

---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: pdk-pvc
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 200Gi
EOF
```

Now run this command to create the PV and PVC for the *gpu-pool* namespace:

```bash
kubectl -n gpu-pool apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-gpu
spec:
  capacity:
    storage: 200Gi
  accessModes:
    - ReadWriteMany
  nfs:
    server: nfs-server.default.svc.cluster.local
    path: "/"

---
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  name: pdk-pvc
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 200Gi
EOF
```


&nbsp;
<a name="step15">
### Step 15 - Create configuration .yaml file for MLDM and MLDE
</a>

This command will create a .yaml file that you can review in a text editor.

```bash
cat <<EOF > helm_values.yaml
deployTarget: "GOOGLE"

pachd:
  enabled: true
  lokiDeploy: true
  lokiLogging: true
  storage:
    google:
      bucket: "${MLDM_BUCKET_NAME}"
  serviceAccount:
    additionalAnnotations:
      iam.gke.io/gcp-service-account: "${SERVICE_ACCOUNT}"
    create: true
    name: "pachyderm"
  worker:
    serviceAccount:
      additionalAnnotations:
        iam.gke.io/gcp-service-account: "${SERVICE_ACCOUNT}"
      create: true
      name: "pachyderm-worker"

cloudsqlAuthProxy:
  enabled: true
  connectionName: ${CLOUDSQL_CONNECTION_NAME}
  serviceAccount: "${SERVICE_ACCOUNT}"
  resources:
    requests:
      memory: "500Mi"
      cpu:    "250m"

postgresql:
  enabled: false

global:
  postgresql:
    postgresqlHost: "cloudsql-auth-proxy.default.svc.cluster.local."
    postgresqlPort: "5432"
    postgresqlSSL: "disable"
    postgresqlUsername: "postgres"
    postgresqlPassword: "${SQL_ADMIN_PASSWORD}"

loki-stack:
  loki:
    env:
    - name: GOOGLE_APPLICATION_CREDENTIALS
      value: /etc/secrets/${LOKI_GSA_NAME}-key.json
    extraVolumes:
      - name: loki-service-account
        secret:
          secretName: loki-service-account
    extraVolumeMounts:
      - name: loki-service-account
        mountPath: /etc/secrets
    config:
      schema_config:
        configs:
        - from: 1989-11-09
          object_store: gcs
          store: boltdb
          schema: v11
          index:
            prefix: loki_index_
          chunks:
            prefix: loki_chunks_
      storage_config:
        gcs:
          bucket_name: "${LOKI_BUCKET_NAME}"
        # https://github.com/grafana/loki/issues/256
        bigtable:
          project: project
          instance: instance
        boltdb:
          directory: /data/loki/indices
  grafana:
    enabled: false

proxy:
  enabled: true
  service:
    type: LoadBalancer
    loadBalancerIP: ${STATIC_IP_ADDR}
    httpPort: 80
    httpsPort: 443
  tls:
    enabled: false
  
determined:
  enabled: true
  detVersion: "0.28.1"
  imageRegistry: determinedai
  enterpriseEdition: false
  imagePullSecretName:
  masterPort: 8080
  createNonNamespacedObjects: true
  useNodePortForMaster: true
  defaultPassword: ${ADMIN_PASSWORD}
  db:
    hostAddress: "cloudsql-auth-proxy.default.svc.cluster.local."
    name: determined
    user: postgres
    password: ${SQL_ADMIN_PASSWORD}
    port: 5432
  checkpointStorage:
    saveExperimentBest: 0
    saveTrialBest: 1
    saveTrialLatest: 1
    type: gcs
    bucket: ${MLDE_BUCKET_NAME}
  maxSlotsPerPod: 4
  masterCpuRequest: "2"
  masterMemRequest: 8Gi
  taskContainerDefaults:
    cpuImage: determinedai/environments:py-3.8-pytorch-1.12-tf-2.11-cpu-6eceaca
    gpuImage: determinedai/environments:cuda-11.3-pytorch-1.12-tf-2.11-gpu-6eceaca
    cpuPodSpec:
      apiVersion: v1
      kind: Pod
      spec:
        containers:
          - name: determined-container
            volumeMounts:
              - name: pdk-pvc-nfs
                mountPath: /run/determined/workdir/shared_fs
        volumes:
          - name: pdk-pvc-nfs
            persistentVolumeClaim:
              claimName: pdk-pvc
    gpuPodSpec:
      apiVersion: v1
      kind: Pod
      spec:
        containers:
          - name: determined-container
            volumeMounts:
              - name: pdk-pvc-nfs
                mountPath: /run/determined/workdir/shared_fs
        volumes:
          - name: pdk-pvc-nfs
            persistentVolumeClaim:
              claimName: pdk-pvc
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
                  - name: pdk-pvc-nfs
                    mountPath: /run/determined/workdir/shared_fs
            volumes:
              - name: pdk-pvc-nfs
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
                  - name: pdk-pvc-nfs
                    mountPath: /run/determined/workdir/shared_fs
            volumes:
              - name: pdk-pvc-nfs
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
<a name="step16">
### Step 16 - Install MLDM and MLDE using Helm
</a>

First, download the charts for MLDM:

```bash
helm repo add pachyderm https://helm.pachyderm.com

helm repo update
```

Then run the installer, referencing the .yaml file you just created:

```bash
helm install pachyderm -f ./helm_values.yaml pachyderm/pachyderm --namespace default
```

Once the installation is complete, annotate the MLDE service accounts so they have access to the storage bucket:

```bash
kubectl annotate serviceaccount default \
  -n default \
  iam.gke.io/gcp-service-account=${SERVICE_ACCOUNT}

kubectl annotate serviceaccount determined-master-pachyderm \
  -n default \
  iam.gke.io/gcp-service-account=${SERVICE_ACCOUNT}
```

Give it a couple of minutes for all the services to be up and running. You can run `kubectl get pods` to see if any pods failed or are stuck. Wait until all pods are running before continuing.


&nbsp;
<a name="step17">
### Step 17 - Create new Ingress for MLDE
</a>

Because we're using a static IP, we'll need to create an ingress for MLDE.

Use this command to create the new ingress:

```bash
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mlde-ingress
  namespace: default
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "160m"  
spec:
  ingressClassName: nginx
  rules:
  - http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: determined-master-service-pachyderm
            port:
              number: 8080
EOF
```

&nbsp;
<a name="step18">
### Step 18 - Retrieve MLDM and MLDE IP addresses and configure command line clients
</a>

In this step, we'll configure the `pachctl` and `det` clients. This will be important later, as we create the project, repo and pipeline for the PDK environment.

```bash
export STATIC_IP_ADDR_NO_QUOTES=$(echo "$STATIC_IP_ADDR" | tr -d '"')

export PACH_URL="http://${STATIC_IP_ADDR_NO_QUOTES}:80"

echo "MLDM Address: http://${STATIC_IP_ADDR_NO_QUOTES}:80"

pachctl connect ${PACH_URL}

pachctl config set active-context ${PACH_URL}
```

At this time, you should be able to access the MLDM UI using the URL that was printed in the terminal:

![alt text][gcp_mldm_01_dashboard]

[gcp_mldm_01_dashboard]: images/gcp_mldm_01_dashboard.png "MLDM Dashboard"

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
export MLDE_STATIC_IP_ADDR_NO_QUOTES=$(echo "$MLDE_STATIC_IP_ADDR" | tr -d '"')

echo "MLDE Address: http://${MLDE_STATIC_IP_ADDR_NO_QUOTES}:80"

export DET_MASTER=${MLDE_STATIC_IP_ADDR_NO_QUOTES}:80

echo ${ADMIN_PASSWORD}

det u login admin
```
(use the password that was displayed in the previous command)

Once logged in, you can run `det e list`, which should return an empty list. If you get an error message, check the MLDE pod and service for errors.

You should also be able to access the MLDE UI using the URL printed on the terminal. Login as user <b>admin</b> (leave password field empty). Once logged in, check the <b>Cluster</b> page and make sure the GPU resources are showing up:

![alt text][gcp_mlde_02_dashboard]

[gcp_mlde_02_dashboard]: images/gcp_mlde_02_dashboard.png "MLDE Dashboard"




&nbsp;
<a name="step19">
### Step 19 - (Optional) Test Components
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


![alt text][gcp_mldm_01_opencv_pipeline]

[gcp_mldm_01_opencv_pipeline]: images/gcp_mldm_01_opencv_pipeline.png "MLDM Pipeline"


&nbsp;

You should also be able to see the <i>chunks</i> in the storage bucket. This confirms that MLDM is able to connect to the bucket.


![alt text][gcp_mldm_02_opencv_storage_buckets]

[gcp_mldm_02_opencv_storage_buckets]: images/gcp_mldm_02_opencv_storage_buckets.png "MLDM Storage bucket"

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


![alt text][gcp_mlde_01_experiment_1_checkpoints]

[gcp_mlde_01_experiment_1_checkpoints]: images/gcp_mlde_01_experiment_1_checkpoints.png "MLDE Experiment - Checkpoints"

&nbsp;

You can also check the MLDE bucket in Google Cloud Storage to see the checkpoints that were saved:

![alt text][gcp_mlde_02_experiment_1_bucket]

[gcp_mlde_02_experiment_1_bucket]: images/gcp_mlde_02_experiment_1_bucket.png "MLDE Storage bucket"


This confirms that MLDE is able to access the Storage buckets as well.


&nbsp;

Finally, go to the MLDE **Home Page** and click the **Launch JupyterLab** button. In the configuration pop-up, select the *Uncategorized* workspace, set the *Resource Pool* to **gpu-pool** (this is important, because the *default* pool has no GPUs available) and set the number of *Slots* (GPUs) to 1. Or set the number of slots to 0 and select the *default* Resource Pool to create a CPU-based notebook environment.

Click **Launch** to start the JupyterLab environment.

The first run should take about one minute to pull and run the image.


![alt text][aws_mlde_06_jupyter]

[aws_mlde_06_jupyter]: images/aws_mlde_06_jupyter.png "MLDE Launch JupyterLab"


In the new tab, make sure the *shared_fs* folder is listed. In this folder, users will be able to permanently store their model assets, notebooks and other files.

![alt text][gcp_mlde_07_shared_folder]

[gcp_mlde_07_shared_folder]: images/gcp_mlde_07_shared_folder.png "MLDE Notebook Shared Folder"

PS: If the JupyterLab environment fails to load, it might be because the shared volume failed to mount. Run `kubectl -n gpu-pool describe pod` against the new pod to see why the pod failed to run.



&nbsp;
<a name="step20">
### Step 20 - Prepare for PDK Setup
</a>

These next steps will help us verify that KServe is working properly, and they will also setup some pre-requisites for the PDK flow (specifically, the step where models are deployed to KServe).

A deeper explanation of the PDK flow is provided in [main deployment page](./README.md); for now, let's make sure KServe is working as expected.

First, create a new namespace that will be used to serve models (through KServe):

```bash
kubectl create namespace ${KSERVE_MODELS_NAMESPACE}
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

It should go from <b>Unknown</b> to <b>Ready</b>, which means the deployment was successful.

![alt text][kserve_01_samplemodel]

[kserve_01_samplemodel]: images/kserve_01_samplemodel.png "KServe Sample Model"


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


![alt text][gcp_kserve_02_ingress]

[gcp_kserve_02_ingress]: images/gcp_kserve_02_ingress.png "KServe Ingress"


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

![alt text][gcp_kserve_03_sample_prediction]

[gcp_kserve_03_sample_prediction]: images/gcp_kserve_03_sample_prediction.png "KServe Sample Prediction"


Make sure you get a valid response before continuing, as the deployment will fail if KServer is not properly setup.

The last part of this step is basically some housekeeping tasks to set the stage for the PDK flow.

First, we create a secret that will store variables that will be used by both MLDM pipelines and MLDE experiments.

```bash
cat <<EOF > "./pipeline-secret.yaml"
apiVersion: v1
kind: Secret
metadata:
  name: pipeline-secret
stringData:
  det_master: "${MLDE_STATIC_IP_ADDR_NO_QUOTES}:80"
  det_user: "admin"
  det_password: "${ADMIN_PASSWORD}"
  pac_token: ""
  pachd_lb_service_host: "${STATIC_IP_ADDR_NO_QUOTES}"
  pachd_lb_service_port: "80"
  kserve_namespace: "${KSERVE_MODELS_NAMESPACE}"
EOF
```

A more detailed explanation of these attributes:

- `det_master`: The address to the MLDE instance. Instead of using a URL, you can also point it to the service running in the default namespace (`determined-master-service-determinedai`).
- `det_user`: MLDE user that will create experiments and pull models.
- `det_password`: Password to the user specified above
- `pac_token`: For the Enterprise version of Pachyderm, create an authentication token for a user. Otherwise, if you use the community edition, leave it blank.
- `kserve_namespace`: Namespace where MLDM will deploy models to

&nbsp;

This will be used by the MLDM pipelines (that will then map the variables to the MLDE experiment):

```bash
kubectl apply -f pipeline-secret.yaml
```

&nbsp;

Next, the MLDM Worker service account (which will be used to run the pods that contain the pipeline code) needs to gain access to the new 'models' namespace, or it won't be able to deploy models there.

First, create the configuration file:

```bash
kubectl apply -f - <<EOF
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

For the next step, the model deployments will need to download from the storage buckets. Since these models will run in the new 'models' namespace, the default service account in this namespace needs to be granted permissions to the bucket:

```bash
kubectl annotate serviceaccount default \
  -n ${KSERVE_MODELS_NAMESPACE} \
  iam.gke.io/gcp-service-account=${SERVICE_ACCOUNT}

gcloud iam service-accounts add-iam-policy-binding ${SERVICE_ACCOUNT} \
    --role roles/iam.workloadIdentityUser \
    --member "${MLDE_KS_WI}"
```

&nbsp;

Finally, create dummy credentials to allow access to the MLDM repo through the S3 protocol.

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
<a name="step21">
### Step 21 - [Optional] Configure KServe UI
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

Then, create a static IP for the KServe UI:

```bash
gcloud compute addresses create ${KSERVE_STATIC_IP_NAME} --region=${GCP_REGION}

export KSERVE_STATIC_IP_ADDR=$(gcloud compute addresses describe ${KSERVE_STATIC_IP_NAME} --region=${GCP_REGION} --format=json --flatten=address | jq '.[]' )

echo $KSERVE_STATIC_IP_ADDR
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
        - "0.0.0.0:8080"
        - "--access-logfile"
        - "-"
        - "entrypoint:app"
        resources:
          limits:
            memory: "1Gi"
            cpu: "500m"
        ports:
        - containerPort: 8080
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
  loadBalancerIP: ${KSERVE_STATIC_IP_ADDR}
  selector:
    app: models-webapp
  ports:
  - port: 8080
    targetPort: 8080
EOF
```

PS: If you would like to build your own image, this Github page contains the source:<br/>
https://github.com/kserve/models-web-app/tree/master

Next, get the URL for the KServe UI:

```bash
export KSERVE_UI_IP=$(kubectl -n ${KSERVE_MODELS_NAMESPACE} get svc model-webapp-service -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

export KSERVE_UI_URL="http://${KSERVE_UI_IP}:8080/"

echo $KSERVE_UI_URL
```

You can access the URL to see the deployed model (make sure to select the correct namespace).


![alt text][gcp_kserve_03_ui]

[gcp_kserve_03_ui]: images/gcp_kserve_03_ui.png "KServe UI"








&nbsp;
<a name="step22">
### Step 22 - [Optional] Prepare Docker and the Container Registry
</a>

The samples provided here already contain images you can use for training and deployment. This step is only necessary if you want to build your own images. In this case, you will find the Dockerfiles for each example in this repository.

First, make sure Docker Desktop is running.

Since each PDK use case will likely need to use specific images, a registry will be required to host these. In this tutorial, we will use Google Artifact Registry, but you can use any other alternative.

Run this command to configure docker for the Google Cloud registry:

```bash
gcloud auth configure-docker
```

Go to the Google Artifact Registry UI and create a new repository. Once the repository is created, the path to the repository will be:

&nbsp;
`<region>-docker.pkg.dev/<project_id>/<repository_name>`
&nbsp;


![alt text][gcp_artifact_registry]

[gcp_artifact_registry]: images/gcp_artifact_registry.png "Artifact Registry"

Since the cluster is also running on GCP, with your credentials, the images will be acessible by the PDK components even if they are private. However, they can also be made public, by granting the `Artifact Registry Reader` permission to `allUsers`. Do keep in mind that this will make the images public to anyone on the internet.


![alt text][gcp_artifact_repo_reader]

[gcp_artifact_repo_reader]: images/gcp_artifact_repo_reader.png "Artifact Registry"


PS: when pushing images to GCP, it's a good idea to prefix with your name, to avoid confusing with other users' images.

Next, set the registry path as a variable and use these commands will download the busybox image from dockerhub and push it to GCP:

```bash
export REGISTRY_URL=${GCP_REGION}-docker.pkg.dev/${PROJECT_ID}/pdk-registry

docker pull busybox:latest

docker tag busybox:latest ${REGISTRY_URL}/busybox

docker push ${REGISTRY_URL}/busybox
```

You can also see the new image in your Docker Desktop dashboard:

![alt text][gcp_docker_01_busybox]

[gcp_docker_01_busybox]: images/gcp_docker_01_busybox.png "Docker busybox image"


&nbsp;

You can also check the Artifact Registry UI in the Google Cloud Console (you might need to search for it) and make sure the new image is there:

![alt text][gcp_registry_busybox]

[gcp_registry_busybox]: images/gcp_registry_busybox.png "GCP Artifact Registry"


&nbsp;

&nbsp;
<a name="step23">
### Step 23 - Save data to Config Map
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
  region: "${GCP_REGION}"
  mldm_bucket_name: "${MLDM_BUCKET_NAME}"
  mldm_host: "${STATIC_IP_ADDR_NO_QUOTES}"
  mldm_port: "80"
  mldm_url: "${PACH_URL}"
  mldm_pipeline_secret: "pipeline-secret"
  mlde_bucket_name: "${MLDE_BUCKET_NAME}"
  mlde_host: "${MLDE_STATIC_IP_ADDR_NO_QUOTES}"
  mlde_port: "80"
  mlde_url: "http://${MLDE_STATIC_IP_ADDR_NO_QUOTES}:80"
  kserve_ui_url: "${KSERVE_UI_URL}"
  model_assets_bucket_name: "${MODEL_ASSETS_BUCKET_NAME}"
  kserve_model_namespace: "${KSERVE_MODELS_NAMESPACE}"
  kserve_ingress_host: "${INGRESS_HOST}"
  kserve_ingress_port: "${INGRESS_PORT}"
  db_connection_string: ${CLOUDSQL_CONNECTION_NAME}
  registry_uri: "${REGISTRY_URL}"
  pdk_name: "${NAME}"
EOF
```

Next, create the configmap:

```bash
kubectl apply -f ./pdk-config.yaml
```

Once the config map is created, you can run `kubectl get cm pdk-config -o yaml` to verify the data.

&nbsp;
<a name="step24">
### Step 24 - Create Cleanup Script
</a>

In this ste, we create a script that will delete all components created as part of this installation.

```bash
cat <<EOF > ./_cleanup.sh
# DELETE CLUSTER
printf 'yes' | gcloud container clusters delete ${CLUSTER_NAME}

# Delete DB
printf 'yes' | gcloud sql instances delete ${CLOUDSQL_INSTANCE_NAME}

# Delete buckets
printf 'yes' | gcloud storage rm --recursive gs://${MLDM_BUCKET_NAME}
printf 'yes' | gcloud storage rm --recursive gs://${MLDE_BUCKET_NAME}
printf 'yes' | gcloud storage rm --recursive gs://${LOKI_BUCKET_NAME}
printf 'yes' | gcloud storage rm --recursive gs://${MODEL_ASSETS_BUCKET_NAME}

# Delete Static IPs
printf 'yes' | gcloud compute addresses delete ${STATIC_IP_NAME}
printf 'yes' | gcloud compute addresses delete ${MLDE_STATIC_IP_NAME}
printf 'yes' | gcloud compute addresses delete ${KSERVE_STATIC_IP_NAME}

# Delete Role
printf 'yes' | gcloud iam roles delete ${GSA_ROLE_NAME} --project ${PROJECT_ID}

# Delete Shared Disk
printf 'yes' | gcloud compute disks delete --zone=${GCP_ZONE} ${NAME}-pdk-nfs-disk

# Delete Service Accounts
printf 'yes' | gcloud iam service-accounts delete ${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com
printf 'yes' | gcloud iam service-accounts delete ${LOKI_GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com

EOF

chmod +x _cleanup.sh
```

When it's time to cleanup your environment, just run:
```bash
./_cleanup.sh
```


</a>


&nbsp;
<a name="commands">
## GCP - Useful Commands
</a>

### Creating folders in the GCP bucket

GCP doesn't allow empty folders on buckets, and the MLDM pipeline will fail if the folder doesn't exist, so we'll create the folders with dummy files, to make sure the bucket is ready for the pipelines:

```bash
echo "hello world" > helloworld.txt

gsutil cp helloworld.txt gs://${MODEL_ASSETS_BUCKET_NAME}/dogs-and-cats/config/hello.txt

gsutil cp helloworld.txt gs://${MODEL_ASSETS_BUCKET_NAME}/dogs-and-cats/model-store/hello.txt
```

&nbsp;

### Retrieve MLDE Admin Password

The MLDE admin password is stored in a secret, with base64 encoding. Use this command to retrieve the decoded password value:

```bash
kubectl get secret pipeline-secret -o jsonpath="{.data.det_password}" | base64 --decode
```


&nbsp;

---

&nbsp;

The installation steps are now completed. At this time, you have a working cluster, with MLDM, MLDE and KServe deployed.

Next, return to [the main page](README.md) to go through the steps to prepare and deploy the PDK flow for the dogs-and-cats demo.

<br/><br/>
