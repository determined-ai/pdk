![alt text][hpe_logo]

[hpe_logo]: images/hpe_logo.png "HPE Logo"


# PDK - Pachyderm | Determined | KServe
## Deployment Guide for AWS


This guide will walk you through the steps of deploying the PDK components to AWS.


## Reference Architecture
The installation will be performed on the following hardware:

- 3x m5.2xlarge CPU-based nodes (8 vCPUs, 32GB RAM, 1000GB HDD)
- 1x g4dn.metal GPU-based nodes (8 NVIDIA-T4, 96 vCPUs, 384GB RAM, 1000GB HDD)

The 3 CPU-based nodes will be used to run the services for all 3 products, and the MLDM pipelines. The GPU-based node will be used to run MLDE experiments.

The following software versions will be used for this installation:

- Python: 3.8 and 3.9
- Kubernetes (K8s): 1.24.0
- Postgres: 13
- MLDE (Determined.AI): latest *(currently 0.26.0)*
- MLDM (Pachyderm): latest *(currently 2.7.4)*
- KServe: 0.11.0rc1 (Quickstart Environment)

PS: some of the commands used here are sensitive to the version of the product(s) listed above.


## Prerequisites
To follow this documentation you will need:

- The following applications, installed and configured in your computer:
  - kubectl
  - docker (you'll need docker desktop or similar to create and push images)
  - git (you'll need to be logged in to your github account to pull code for the MLDM pipelines)
  - aws cli (make sure it's initialized and logged in; basic client configuration is out of scope for this doc)
  - eksctl (to create the EKS cluster)
  - helm
  - jq
  - patchctl (the MLDM command line client)
  - det (the MLDE command line client)
- Access to an AWS account
- A user with enough permissions to provision all the necessary components

&nbsp;

--------

## Installing the Cluster

In this page, we will execute the following steps:

[01 - Set Environment Variables](#step1)

[02 - Test the pre-req client applications](#step2)

[03 - Create the S3 Buckets](#step3)

[04 - Create the EKS cluster](#step4)

[05 - Connect to the EKS cluster](#step5)

[06 - Configure the GPU nodes](#step6)

[07 - Configure Shared Storage and the Storage Classes](#step7)

[08 - Configure Kubernetes Autoscaler](#step8)

[09 - Create Postgres Database](#step9)

[10 - Create configuration .yaml file for MLDM](#step10)

[11 - Install MLDM using Helm](#step11)

[12 - Retrieve MLDM IP address and configure pachctl command line](#step12)

[13 - Deploy nginx for MLDE](#step13)

[14 - Prepare MLDE installation assets](#step14)

[15 - Deploy MLDE using Helm chart](#step15)

[16 - Create new Ingress for MLDE](#step16)

[17 - Deploy KServe](#step17)

[18 - (Optional) Test Components](#step18)

[19 - Prepare for PDK Setup](#step19)

[19b - [Optional] Configure KServe UI](#step19b)

[20 - Prepare Docker and ECR to manage images](#step20)

[21 - Save data to Config Map](#step21)

<br/>

There is also a list of AWS-specific [Useful Commands](#commands) at the bottom of the page.


#### IMPORTANT: These steps were created and tested on an M1 MacOS computer. Some of the commands might work differently (or not at all) in other operating systems. Check the command documentation for an alternative syntax, if you are using a different OS.

#### NOTE: It's recommended to run these instructions one at a time, so you can diagnose in case of issues. The syntax for some of the commands documented here might become invalid, as new versions of these applications are released.


&nbsp;
<a name="step1">
### Step 1 - Set Environment Variables
</a>

These steps will require an existing VPC with 3 Subnets and at least 1 Security Group. Removing the VPC settings from the EKS configuration YAML file will cause the installer to create a new VPC with new Subnets. In this case, you will need to modify the RDS installation call to use the VPC that was created with EKS.

All commands listed throghout this document must be executed in the same terminal window.


```bash
# MODIFY THESE VARIABLES
export NAME="your-name-pdk"
export RDS_ADMIN_PASSWORD="your-database-password"
export AWS_ACCOUNT_ID="555555555555"

# VPC SETTINGS
export AWS_VPC_ID="vpc-0000000000000000x"
export AWS_VPC_SUBNET_1_ID="subnet-0000000000000000a"
export AWS_VPC_SUBNET_2_ID="subnet-0000000000000000b"
export AWS_VPC_SUBNET_3_ID="subnet-0000000000000000c"
export AWS_VPC_SECGROUP_ID="sg-0000000000000000a"

# IAM SETTINGS
export IAM_EBSCSIDRIVERPOLICY="arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
export IAM_EFSCSIDRIVERPOLICY="arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy"

# These can be modified as needed
export AWS_REGION="us-east-2"
export AWS_AVAILABILITY_ZONE_1="us-east-2a"
export AWS_AVAILABILITY_ZONE_2="us-east-2b"
export AWS_AVAILABILITY_ZONE_3="us-east-2c"
export MLDM_NAMESPACE="pachyderm"
export KSERVE_MODELS_NAMESPACE="models"
export CLUSTER_MACHINE_TYPE="m5.2xlarge"
export GPU_MACHINE_TYPE="g4dn.metal"
export RDS_INSTANCE_CLASS="db.m6gd.large"

# You should not need to modify any of these variables
export CLUSTER_NAME="${NAME}-cluster"
export MLDM_BUCKET_NAME="${NAME}-repo-mldm"
export MLDE_BUCKET_NAME="${NAME}-repo-mlde"
export MODEL_ASSETS_BUCKET_NAME="${NAME}-repo-models"
export RDS_INSTANCE_NAME="${NAME}-rds"
export RDS_SUBNET_NAME="${NAME}-rds-subnet"
```



&nbsp;
<a name="step2">
### Step 2 - Test the pre-req client applications
</a>

Make sure all these commands return successfully. If one of them fails, fix the issue before continuing.

```bash
kubectl version --client=true
aws --version
eksctl version
helm version
pachctl version
det version
jq --version
```

&nbsp;
<a name="step3">
### Step 3 - Create the S3 Buckets
</a>

Run these commands to create the 2 buckets that will be used for PDK

```bash
aws s3 mb s3://${MLDM_BUCKET_NAME} --region ${AWS_REGION}

aws s3 mb s3://${MLDE_BUCKET_NAME} --region ${AWS_REGION}

aws s3 mb s3://${MODEL_ASSETS_BUCKET_NAME} --region ${AWS_REGION}
```


&nbsp;
<a name="step4">
### Step 4 - Create the EKS cluster
</a>

First, create the configuration file for the new cluster:

```bash
cat <<EOF > ./eks-config.yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: ${CLUSTER_NAME}
  region: ${AWS_REGION}
  version: "1.24"

# Use Existing VPC
vpc:
  id: "${AWS_VPC_ID}"
  sharedNodeSecurityGroup: "${AWS_VPC_SECGROUP_ID}"
  subnets:
    public:
      public-one:
          id: "${AWS_VPC_SUBNET_1_ID}"
      public-two:
          id: "${AWS_VPC_SUBNET_2_ID}"
      public-three:
          id: "${AWS_VPC_SUBNET_3_ID}"

iam:
  withOIDC: true
  serviceAccounts:
  - metadata:
      name: "checkpoint-storage-s3-bucket"
      namespace: "default"
      labels:
        aws-usage: "determined-checkpoint-storage"
    roleName: "eksctl-${CLUSTER_NAME}-mlde-role"
    attachPolicyARNs:
    - ${IAM_EFSCSIDRIVERPOLICY}
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "s3:ListBucket"
        Resource: "arn:aws:s3:::${MLDE_BUCKET_NAME}"
      - Effect: Allow
        Action:
        - "s3:GetObject"
        - "s3:PutObject"
        - "s3:DeleteObject"
        Resource: "arn:aws:s3:::${MLDE_BUCKET_NAME}/*"
  - metadata:
      name: "checkpoint-storage-s3-bucket"
      namespace: "gpu-pool"
      labels:
        aws-usage: "determined-checkpoint-storage"
    roleName: "eksctl-${CLUSTER_NAME}-mlde-gpu-role"
    attachPolicyARNs:
    - ${IAM_EFSCSIDRIVERPOLICY}
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "s3:ListBucket"
        Resource: "arn:aws:s3:::${MLDE_BUCKET_NAME}"
      - Effect: Allow
        Action:
        - "s3:GetObject"
        - "s3:PutObject"
        - "s3:DeleteObject"
        Resource: "arn:aws:s3:::${MLDE_BUCKET_NAME}/*"
  - metadata:
      name: "pachyderm"
      namespace: "${MLDM_NAMESPACE}"
      labels:
        aws-usage: "pachyderm-bucket-access"
    roleName: "eksctl-${CLUSTER_NAME}-mldm-role"
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "s3:ListBucket"
        Resource: [
          "arn:aws:s3:::${MLDM_BUCKET_NAME}",
          "arn:aws:s3:::${MLDE_BUCKET_NAME}",
          "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}"
        ]
      - Effect: Allow
        Action:
        - "s3:GetObject"
        - "s3:PutObject"
        - "s3:DeleteObject"
        Resource: [
          "arn:aws:s3:::${MLDM_BUCKET_NAME}/*",
          "arn:aws:s3:::${MLDE_BUCKET_NAME}/*",
          "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}/*"
        ]
  - metadata:
      name: "pachyderm-worker"
      namespace: "${MLDM_NAMESPACE}"
      labels:
        aws-usage: "pachyderm-bucket-access"
    roleName: "eksctl-${CLUSTER_NAME}-mldm-worker-role"
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "s3:ListBucket"
        Resource: [
          "arn:aws:s3:::${MLDM_BUCKET_NAME}",
          "arn:aws:s3:::${MLDE_BUCKET_NAME}",
          "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}"
        ]
      - Effect: Allow
        Action:
        - "s3:GetObject"
        - "s3:PutObject"
        - "s3:DeleteObject"
        Resource: [
          "arn:aws:s3:::${MLDM_BUCKET_NAME}/*",
          "arn:aws:s3:::${MLDE_BUCKET_NAME}/*",
          "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}/*"
        ]
  - metadata:
      name: "default"
      namespace: "${KSERVE_MODELS_NAMESPACE}"
      labels:
        aws-usage: "kserve-bucket-access"
    roleName: "eksctl-${CLUSTER_NAME}-kserve-role"
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "s3:ListBucket"
        Resource: "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}"
      - Effect: Allow
        Action:
        - "s3:GetObject"
        - "s3:PutObject"
        - "s3:DeleteObject"
        Resource: "arn:aws:s3:::${MODEL_ASSETS_BUCKET_NAME}/*"
  - metadata:
      name: "cluster-autoscaler"
      namespace: "kube-system"
      labels:
        aws-usage: "pdk-cluster-autoscaler"
    roleName: "eksctl-${CLUSTER_NAME}-autoscaler-role"
    wellKnownPolicies:
      autoScaler: true
    attachPolicy:
      Version: "2012-10-17"
      Statement:
      - Effect: Allow
        Action:
        - "autoscaling:DescribeAutoScalingGroups"
        - "autoscaling:DescribeAutoScalingInstances"
        - "autoscaling:DescribeLaunchConfigurations"
        - "autoscaling:DescribeScalingActivities"
        - "autoscaling:DescribeInstances"
        - "autoscaling:DescribeTags"
        - "autoscaling:SetDesiredCapacity"
        - "autoscaling:TerminateInstanceInAutoScalingGroup"
        - "ec2:DescribeLaunchTemplateVersions"
        - "ec2:DescribeImages"
        - "ec2:DescribeInstanceTypes"
        - "ec2:GetInstanceTypesFromInstanceRequirements"
        - "eks:DescribeNodegroup"
        Resource: '*'

managedNodeGroups:
  - name: managed-cpu-nodes
    instanceType: ${CLUSTER_MACHINE_TYPE}
    availabilityZones:
      - ${AWS_AVAILABILITY_ZONE_1}
      - ${AWS_AVAILABILITY_ZONE_2}
      - ${AWS_AVAILABILITY_ZONE_3}
    minSize: 3
    maxSize: 4
    volumeSize: 1000
    volumeType: gp3
    iam:
      withAddonPolicies:
        autoScaler: true
        cloudWatch: true
        ebs: true
        efs: true
    ssh:
      allow: true
    labels:
      nodegroup-type: cpu-${AWS_AVAILABILITY_ZONE_1}
      nodegroup-role: cpu-worker
    tags:
      k8s.io/cluster-autoscaler/enabled: "true"
      k8s.io/cluster-autoscaler/user-eks: "owned"
      k8s.io/cluster-autoscaler/${CLUSTER_NAME}: "owned"
      k8s.io/cluster-autoscaler/node-template/label/nodegroup-type: cpu-${AWS_AVAILABILITY_ZONE_1}
      k8s.io/cluster-autoscaler/node-template/label/nodegroup-role: cpu-worker

  - name: managed-gpu-nodes
    instanceType: ${GPU_MACHINE_TYPE}
    # Restrict to a single AZ to optimize data transfer between instances
    availabilityZones:
      - ${AWS_AVAILABILITY_ZONE_1}
    minSize: 1
    maxSize: 2
    volumeSize: 1000
    volumeType: gp3
    iam:
      withAddonPolicies:
        autoScaler: true
        cloudWatch: true
        ebs: true
        efs: true
    ssh:
      allow: true
    labels:
      nodegroup-type: gpu-${AWS_AVAILABILITY_ZONE_1}
      nodegroup-role: gpu-worker
      k8s.amazonaws.com/accelerator: nvidia-tesla-t4
      nvidia.com/gpu: "true"
    taints:
      - key: nvidia.com/gpu
        value: "present"
        effect: NoSchedule
    tags:
      k8s.io/cluster-autoscaler/enabled: "true"
      k8s.io/cluster-autoscaler/user-eks: "owned"
      k8s.io/cluster-autoscaler/${CLUSTER_NAME}: "owned"
      k8s.io/cluster-autoscaler/node-template/label/nodegroup-type: gpu-${AWS_AVAILABILITY_ZONE_1}
      k8s.io/cluster-autoscaler/node-template/label/nodegroup-role: gpu-worker
      k8s.io/cluster-autoscaler/node-template/taint/dedicated: nvidia.com/gpu=present
      k8s.io/cluster-autoscaler/node-template/label/nvidia.com/gpu: "true"

addons:
- name: aws-ebs-csi-driver
  attachPolicyARNs:
    - ${IAM_EBSCSIDRIVERPOLICY}
  resolveConflicts: overwrite
- name: aws-efs-csi-driver
  attachPolicyARNs:
    - ${IAM_EFSCSIDRIVERPOLICY}
  resolveConflicts: overwrite
EOF
```

&nbsp;

Next, create the EKS cluster:

```bash
eksctl create cluster --config-file eks-config.yaml
```

This should take several minutes. Once it's completed, go to the AWS Console, open your cluster and check the **Add-ons** tab; make sure the EBS and EFS drivers are listed as Active (they may show as 'Degraded' for a few minutes).

![alt text][aws_eks_01_ebscluster]

[aws_eks_01_ebscluster]: images/aws_eks_01_ebscluster.png "EBS Driver Add-On"


You can also go to the **IAM -> Roles** page, to see that a number of roles was automatically created. This is done to enable IRSA (IAM Roles for Service Accounts) for the PDK components:

![alt text][aws_eks_02_roles]

[aws_eks_02_roles]: images/aws_eks_02_roles.png "IAM Roles"

These roles will grant permissions to the cluster Autoscaler, and will allow the PDK components to access the S3 buckets.

You can inspect these new roles to see the permissions that are being granted. The Trust relationship tab will show which Kubernetes service accounts are allowed to assume this role at runtime. In this case, we can see that the **pachyderm** service account, in the **$MLDM_NAMESPACE** namespace (also pachyderm in this case) is able to assume this role, which grants permissions on the S3 bucket:

![alt text][aws_eks_03_trust]

[aws_eks_03_trust]: images/aws_eks_03_trust.png "IAM Role - Trust Relationship"




&nbsp;
<a name="step5">
### Step 5 - Connect to the EKS cluster
</a>

Run this command to confirm that the new cluster is available:

```bash
eksctl get clusters
```

PS: If your new cluster does not appear on the list, it could have failed to provision. Otherwise, you might be having issues with conflicting permissions with eksctl. Make sure to fix these issues before continuing.

Use this command to configure the kubectl context:

```bash
aws eks --region ${AWS_REGION} update-kubeconfig --name ${CLUSTER_NAME}
```

You can then run `kubectl get nodes` to make sure you are able to access the cluster.



&nbsp;
<a name="step6">
### Step 6 - Configure the GPU nodes
</a>

Run this command to deploy the GPU daemonset. Without it, your nodes will show 0 allocatable GPUs:

```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.0/nvidia-device-plugin.yml
```

This will take a couple of minutes to take effect. Run a `kubectl get nodes` and then a `kubectl describe node <node_name>` in one of the GPU nodes. Look for the Allocatable section; if you don't see a `nvidia.com/gpu: 8` entry in that list, wait a few seconds and check again. Do not continue until the GPUs are being listed as allocatable.

You can also use this command to list allocatable GPUs per node:

```bash
kubectl describe nodes  |  tr -d '\000' | sed -n -e '/^Name/,/Roles/p' -e '/^Capacity/,/Allocatable/p' -e '/^Allocated resources/,/Events/p'  | grep -e Name  -e  nvidia.com  | perl -pe 's/\n//'  |  perl -pe 's/Name:/\n/g' | sed 's/nvidia.com\/gpu:\?//g'  | sed '1s/^/Node Available(GPUs)  Used(GPUs)/' | sed 's/$/ 0 0 0/'  | awk '{print $1, $2, $3}'  | column -t
```


For the MLDE installation, we'll configure the GPU nodes to be in a separate Resource Pool. This requires a new namespace for the GPU nodes, as experiments will run as pods in that namespace (that will then be bound to the GPU nodes). Because the EKS creation template assigned the necessary permissions to access the S3 bucket, the `gpu-pool` namespace was automatically created, along with the service account.

You can check the service account by running `kubectl -n gpu-pool get sa`.



&nbsp;
<a name="step7">
### Step 7 - Configure Shared Storage and the Storage Classes
</a>

MLDE offers a hosted Jupyter Lab environment, where users can create and run notebooks. This environment needs persistent storage, in order to save user files. This persistent storage must be mounted as a shared folder. In this step, we will configure the necessary components to enable this capability.

First, we need to create a security group that allows inbound NFS access to the EFS volume. Execute these commands to collect the necessary data and create the security group.

```bash
export AWS_VPC_ID=$(aws eks describe-cluster --name ${CLUSTER_NAME} --query 'cluster.resourcesVpcConfig.vpcId' --output text)

export AWS_VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids ${AWS_VPC_ID} --query 'Vpcs[].CidrBlock' --output text)

aws ec2 create-security-group --description ${CLUSTER_NAME}-sg-efs --group-name ${CLUSTER_NAME}-sg-efs --vpc-id ${AWS_VPC_ID}

export SEC_GROUP_ID=$(aws ec2 describe-security-groups \
  --filters Name=vpc-id,Values=${AWS_VPC_ID} Name=group-name,Values=${CLUSTER_NAME}-sg-efs\
  --query 'SecurityGroups[0].GroupId' --output text)


aws ec2 authorize-security-group-ingress --group-id ${SEC_GROUP_ID} --protocol tcp --port 2049 --cidr ${AWS_VPC_CIDR}
```

**IMPORTANT**: This Security group will authorize IPs inside the CIDR range for your VPC. If you have multiple CIDR ranges, you will need to run the `aws ec2 authorize-security-group-ingress` command for every CIDR range, or you risk your nodes not being included in this rule, which will cause the volume to fail to provision. You can use this command to list all CIDR ranges used by your VPC:
```bash
aws ec2 describe-vpcs --vpc-ids ${AWS_VPC_ID} --query 'Vpcs[].CidrBlockAssociationSet'
```
If you see more than one result in this command, run the `authorize-security-group-ingress` for each range in the response.


&nbsp;

Next, create the EFS volume:
```bash
aws efs create-file-system --creation-token ${CLUSTER_NAME}-efs --tags Key=Name,Value=${CLUSTER_NAME}-efs

export EFS_ID=$(aws efs describe-file-systems --creation-token ${CLUSTER_NAME}-efs \
  --query 'FileSystems[0].FileSystemId' --output text)
```

The mount targets need to be created in each Availability Zone. If you are not using a pre-existing VPC, grab the IDs of the Subnets and set the variables before continuing.
```bash
aws efs create-mount-target --file-system-id ${EFS_ID} --subnet-id ${AWS_VPC_SUBNET_1_ID} --security-group ${SEC_GROUP_ID}

aws efs create-mount-target --file-system-id ${EFS_ID} --subnet-id ${AWS_VPC_SUBNET_2_ID} --security-group ${SEC_GROUP_ID}

aws efs create-mount-target --file-system-id ${EFS_ID} --subnet-id ${AWS_VPC_SUBNET_3_ID} --security-group ${SEC_GROUP_ID}
```

This should ensure that the volumes can be mounted by the worker nodes, regardless of the AZ they are running on.

Now let's create the remaining assets.

First, let's setup the gp3 storageclass, which is recommended for MLDM when running on EKS.

Create the storage class:

```bash
kubectl apply -f  - <<EOF
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
  fsType: ext4
EOF
```

Next, annotate the gp2 storageclass so it's no longer set as default:

```bash
kubectl annotate sc gp2 --overwrite=true storageclass.kubernetes.io/is-default-class=false
```

Run `kubectl get sc` to make sure gp3 is the only one set as default.

Next, create the storage class for EFS:
```bash
kubectl apply -f  - <<EOF
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
EOF
```

Now create two Persistent Volumes and two Persistent Volume Claims, which will be associated with the file system we just created. We'll create one PV and one PVC in each namespace that can run MLDE notebooks (*default* and *gpu-pool*). The *default* namespace is created with the Kubernetes cluster, and the EKS installer already created the *gpu-pool* namespace as well (since it needed to grant bucket permissions to it). Run `kubectl get ns` to make sure the *gpu-pool* namespace exists.

PS: We're setting it for 200GB, but you can modify the size as needed.

Run this command to create the first PV and PVC:
```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: efs-pv
spec:
  capacity:
    storage: 200Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-sc
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: efs-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: efs-sc
  resources:
    requests:
      storage: 200Gi
EOF
```

Next, create the second PV and PVC:

```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: efs-pv-gpu
spec:
  capacity:
    storage: 200Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  storageClassName: efs-sc
  csi:
    driver: efs.csi.aws.com
    volumeHandle: ${EFS_ID}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: efs-pvc
  namespace: gpu-pool
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: efs-sc
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





&nbsp;
<a name="step8">
### Step 8 - Configure Kubernetes Autoscaler
</a>

The Kubernetes autoscaler will ensure that new nodes will be added to the cluster in case of resource constraints, and will scale down the cluster when there is not enough activity going on.

First, deploy the autoscaler with the standard configuration:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/autoscaler/master/cluster-autoscaler/cloudprovider/aws/examples/cluster-autoscaler-run-on-control-plane.yaml
```

Then create a new file, to override the default settings for the autoscaler:

```bash
cat <<EOF > determined-autoscaler.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app: cluster-autoscaler
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cluster-autoscaler
  template:
    metadata:
      labels:
        app: cluster-autoscaler
      annotations:
        prometheus.io/scrape: 'true'
        prometheus.io/port: '8085'
    spec:
      serviceAccountName: cluster-autoscaler
      tolerations:
        - key: node-role.kubernetes.io/master
          operator: "Equal"
          value: "true"
          effect: NoSchedule
      containers:
        - image: k8s.gcr.io/autoscaling/cluster-autoscaler:v1.24.0
          name: cluster-autoscaler
          resources:
            limits:
              cpu: 100m
              memory: 300Mi
            requests:
              cpu: 100m
              memory: 300Mi
          command:
            - ./cluster-autoscaler
            - --v=4
            - --stderrthreshold=info
            - --cloud-provider=aws
            - --skip-nodes-with-local-storage=false
            - --expander=least-waste
            - --scale-down-delay-after-add=5m
            - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/${CLUSTER_NAME}
            - --balance-similar-node-groups
            - --skip-nodes-with-system-pods=false
          volumeMounts:
            - name: ssl-certs
              mountPath: /etc/ssl/certs/ca-certificates.crt
              readOnly: true
          imagePullPolicy: "Always"
      volumes:
        - name: ssl-certs
          hostPath:
            path: "/etc/ssl/certs/ca-bundle.crt"

EOF
```

Apply the new configurations:

```bash
kubectl apply -f determined-autoscaler.yaml
```

Patch the autoscaler:

```bash
kubectl patch deployment cluster-autoscaler \
-n kube-system \
-p '{"spec":{"template":{"metadata":{"annotations":{"cluster-autoscaler.kubernetes.io/safe-to-evict": "false"}}}}}'
```

To make sure the autoscaler is running properly, use these commands to check the deployment and look at the logs:

```bash
kubectl -n kube-system get deploy

kubectl -n kube-system logs -f deployment.apps/cluster-autoscaler
```

The `No candidates for scale down` message in the logs means the autoscaler is working properly. It may take a few seconds to appear, as the changes are being applied. Investigate and fix any issues before continuing.


&nbsp;
<a name="step9">
### Step 9 - Create Postgres Database
</a>

Create a subnet for the new database (or set the **${RDS_SUBNET_NAME}** variable to use an existing one):

```bash
aws rds create-db-subnet-group \
    --db-subnet-group-name ${RDS_SUBNET_NAME} \
    --db-subnet-group-description "Subnet group for database ${RDS_INSTANCE_NAME}" \
    --subnet-ids "${AWS_VPC_SUBNET_1_ID}" "${AWS_VPC_SUBNET_2_ID}" "${AWS_VPC_SUBNET_3_ID}"
```

PS: type `q` to close the output and return to your terminal.


Use the following command to provision a cloud Postgres database. Leave the `--publicly-accessible` flag if you want to access the database from an external client (like DBeaver).

```bash
aws rds create-db-cluster \
    --database-name postgres \
    --db-cluster-identifier ${RDS_INSTANCE_NAME}-cluster \
    --db-cluster-instance-class ${RDS_INSTANCE_CLASS} \
    --engine postgres \
    --engine-version 13.11 \
    --master-user-password ${RDS_ADMIN_PASSWORD} \
    --master-username postgres \
    --allocated-storage 100 \
    --storage-type io1 \
    --iops 3000 \
    --vpc-security-group-ids "${AWS_VPC_SECGROUP_ID}" \
    --availability-zones "${AWS_AVAILABILITY_ZONE_1}" \
    --db-subnet-group-name ${RDS_SUBNET_NAME} \
    --network-type IPV4 \
    --no-auto-minor-version-upgrade \
    --no-enable-performance-insights \
    --publicly-accessible
```

PS: If you want to use Postgres 14, additional configuration steps will be needed, because the default password encryption was changed between versions. Make sure to check the documentation for additional steps.

It will take a few minutes to provision the database. To check the status of the provisioning process, use the AWS Console, or run this command:

```bash
aws rds describe-db-clusters \
    --db-cluster-identifier ${RDS_INSTANCE_NAME}-cluster \
    --query 'DBClusters[0].Status' \
    --output text
```

Wait until the Status returns as `available`. The DB will be then ready for use.

These commands will retrieve and print the connection string for the database:

```bash
export RDS_CONNECTION_URL=$(aws rds describe-db-cluster-endpoints --db-cluster-identifier ${RDS_INSTANCE_NAME}-cluster --filters Name=db-cluster-endpoint-type,Values=WRITER --query 'DBClusterEndpoints[0].Endpoint' --output text)

echo $RDS_CONNECTION_URL
```

At this time, if you set the `--publicly-accessible` flag, you can connect using your external client:


![alt text][aws_rds_01_dbeaver]

[aws_rds_01_dbeaver]: images/aws_rds_01_dbeaver.png "External Postgres client"


The next step is to setup the 3 databases that will be used by PDK. Since the AWS client doesn't have the ability to create databases inside an instance, there are a few options that could be considered:
- Connect the database to an EC2 instance
- Use the external client (DBeaver in this case)
- Use the postgres `psql` command line utility (`psql -h ${RDS_CONNECTION_URL} postgres postgres`)
- Create a pod with psql and connect to the instance

To create the databases using the psql pod, use these commands:


```bash
kubectl run psql -it --rm=true --image=postgres:13 --command -- psql -h ${RDS_CONNECTION_URL} -U postgres postgres

# The prompt will freeze as it waits for the password. Type the password and press enter.

postgres=> CREATE DATABASE pachyderm;

postgres=> CREATE DATABASE dex;

postgres=> CREATE DATABASE determined;

postgres=> GRANT ALL PRIVILEGES ON DATABASE pachyderm TO postgres;

postgres=> GRANT ALL PRIVILEGES ON DATABASE dex TO postgres;

postgres=> GRANT ALL PRIVILEGES ON DATABASE determined TO postgres;
```

PS: In this case, we'll be using the **postgress** user as the main user for MLDE and MLDM. You can create specific users for each product at this time, if needed.

You can get a list of databases by running the `\l` command:

```bash
postgres=> \l
                                                  List of databases
    Name    |  Owner   | Encoding |   Collate   |    Ctype    | ICU Locale | Locale Provider |   Access privileges
------------+----------+----------+-------------+-------------+------------+-----------------+-----------------------
 determined | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | =Tc/postgres         +
            |          |          |             |             |            |                 | postgres=CTc/postgres
 dex        | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | =Tc/postgres         +
            |          |          |             |             |            |                 | postgres=CTc/postgres
 pachyderm  | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | =Tc/postgres         +
            |          |          |             |             |            |                 | postgres=CTc/postgres
 postgres   | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            |
 rdsadmin   | rdsadmin | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | rdsadmin=CTc/rdsadmin+
            |          |          |             |             |            |                 | rdstopmgr=Tc/rdsadmin
 template0  | rdsadmin | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | =c/rdsadmin          +
            |          |          |             |             |            |                 | rdsadmin=CTc/rdsadmin
 template1  | postgres | UTF8     | en_US.UTF-8 | en_US.UTF-8 |            | libc            | =c/postgres          +
            |          |          |             |             |            |                 | postgres=CTc/postgres
(7 rows)
```

When you're done, use the command `\q` to quit.


&nbsp;
<a name="step10">
### Step 10 - Create configuration .yaml file for MLDM
</a>

Because we're using the AWS buckets, there are 2 service accounts in the MLDM namespace that will need access to S3: the main MLDM service account and the `worker` MLDM service account, which runs the pipeline code.

The EKS installation command created the necessary roles with the right permissions, all we need to do is configure the service account to leverage those roles. Run these commands to set the proper ARNs for the roles:

```bash
export SERVICE_ACCOUNT_MLDM="arn:aws:iam::${AWS_ACCOUNT_ID}:role/eksctl-${CLUSTER_NAME}-mldm-role"
export SERVICE_ACCOUNT_MLDM_WORKER="arn:aws:iam::${AWS_ACCOUNT_ID}:role/eksctl-${CLUSTER_NAME}-mldm-worker-role"

echo $SERVICE_ACCOUNT_MLDM
echo $SERVICE_ACCOUNT_MLDM_WORKER
```

&nbsp;

This command will create a .yaml file that you can review in a text editor.

```bash
cat <<EOF > ${NAME}.mldm.values.yaml
deployTarget: "AMAZON"

pachd:
  enabled: true
  storage:
    amazon:
      bucket: "${MLDM_BUCKET_NAME}"
      region: "${AWS_REGION}"
  serviceAccount:
    additionalAnnotations:
      eks.amazonaws.com/role-arn: "${SERVICE_ACCOUNT_MLDM}"
    create: false
    name: "pachyderm"
  worker:
    serviceAccount:
      additionalAnnotations:
        eks.amazonaws.com/role-arn: "${SERVICE_ACCOUNT_MLDM_WORKER}"
      create: false
      name: "pachyderm-worker"

postgresql:
  enabled: false

global:
  postgresql:
    postgresqlHost: "${RDS_CONNECTION_URL}"
    postgresqlPort: "5432"
    postgresqlSSL: "disable"
    postgresqlUsername: "postgres"
    postgresqlPassword: "${RDS_ADMIN_PASSWORD}"

proxy:
  enabled: true
  service:
    type: LoadBalancer
  tls:
    enabled: false
EOF
```


&nbsp;
<a name="step11">
### Step 11 - Install MLDM using Helm
</a>

First, download the charts for MLDM:

```bash
helm repo add pachyderm https://helm.pachyderm.com

helm repo update
```

Then run the installer, referencing the .yaml file you just created:

```bash
helm install pachyderm -f ./${NAME}.mldm.values.yaml pachyderm/pachyderm --namespace ${MLDM_NAMESPACE}
```

Give it a couple of minutes for all the services to be up and running. You can run `kubectl -n ${MLDM_NAMESPACE} get pods` to see if any pods failed or are stuck. Wait until all pods are running before continuing.



&nbsp;
<a name="step12">
### Step 12 - Retrieve MLDM IP address and configure pachctl command line
</a>

In this step, we'll configure the pachctl client. This will be important later, as we create the project, repo and pipeline for the PDK environment.

```bash
export MLDM_HOST=$(kubectl get svc --namespace ${MLDM_NAMESPACE} pachyderm-proxy --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export MLDM_URL="http://${MLDM_HOST}:80"

echo $MLDM_URL

pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}
```

PS: You need a working URL to continue.

At this time, you should be able to access the MLDM UI using the URL that was printed in the terminal:


![alt text][aws_mldm_01_ui]

[aws_mldm_01_ui]: images/aws_mldm_01_ui.png "MLDM Dashboard"



&nbsp;
<a name="step13">
### Step 13 - Deploy nginx for MLDE
</a>

Nginx will be configured to listen on port 80 (instead of the default 8080 used by MLDE).

```bash

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

helm repo update

helm upgrade --install -n ingress-system --create-namespace ingress-nginx ingress-nginx/ingress-nginx

```

PS: This could take a couple of minutes. Run `kubectl -n ingress-system get svc` and make sure that the External IP column is showing a value. If the field is empty (or showing Pending), investigate and fix it before continuing.



&nbsp;
<a name="step14">
### Step 14 - Prepare MLDE installation assets
</a>

First, create a new values.yaml file for the Helm chart:

```bash
cat <<EOF > ${NAME}.mlde.values.yaml
imageRegistry: determinedai
enterpriseEdition: false
imagePullSecretName:
createNonNamespacedObjects: true
masterPort: 8080
useNodePortForMaster: true
db:
  hostAddress: "${RDS_CONNECTION_URL}"
  name: determined
  user: postgres
  password: ${RDS_ADMIN_PASSWORD}
  port: 5432
checkpointStorage:
  saveExperimentBest: 0
  saveTrialBest: 1
  saveTrialLatest: 1
  type: s3
  bucket: ${MLDE_BUCKET_NAME}
maxSlotsPerPod: 4
masterCpuRequest: 4
masterMemRequest: 8Gi
taskContainerDefaults:
  cpuImage: determinedai/environments:py-3.8-pytorch-1.12-tf-2.11-cpu-6eceaca
  gpuImage: determinedai/environments:cuda-11.3-pytorch-1.12-tf-2.11-gpu-6eceaca
  cpuPodSpec:
    apiVersion: v1
    kind: Pod
    spec:
      serviceAccountName: checkpoint-storage-s3-bucket
  gpuPodSpec:
    apiVersion: v1
    kind: Pod
    metadata:
      labels:
        nodegroup-role: gpu-worker
    spec:
      serviceAccountName: checkpoint-storage-s3-bucket
telemetry:
  enabled: true
resource_manager:
  default_aux_resource_pool: default
  default_compute_resource_pool: gpu-pool
resourcePools:
  - pool_name: default
    task_container_defaults:
      cpu_pod_spec:
        apiVersion: v1
        kind: Pod
        spec:
          serviceAccountName: checkpoint-storage-s3-bucket
          containers:
            - name: determined-container
              volumeMounts:
                - name: shared-fs
                  mountPath: /run/determined/workdir/shared_fs
          volumes:
            - name: shared-fs
              persistentVolumeClaim:
                claimName: efs-pvc
  - pool_name: gpu-pool
    max_aux_containers_per_agent: 1
    kubernetes_namespace: gpu-pool
    task_container_defaults:
      gpu_pod_spec:
        apiVersion: v1
        kind: Pod
        spec:
          serviceAccountName: checkpoint-storage-s3-bucket
          containers:
            - name: determined-container
              volumeMounts:
                - name: shared-fs
                  mountPath: /run/determined/workdir/shared_fs
          volumes:
            - name: shared-fs
              persistentVolumeClaim:
                claimName: efs-pvc
          tolerations:
            - key: "nvidia.com/gpu"
              operator: "Equal"
              value: "present"
              effect: "NoSchedule"
EOF
```


&nbsp;
<a name="step15">
### Step 15 - Deploy MLDE using Helm chart
</a>

To deploy MLDE, run these commands:

```bash

helm repo add determined-ai https://helm.determined.ai/

helm repo update

helm install determinedai -f ${NAME}.mlde.values.yaml determined-ai/determined

```

Because MLDE will be deployed to the default namespace, you can check the status of the deployment with `kubectl get pods` and `kubectl get svc`.<br/>
Make sure the pod is running before continuing.


&nbsp;
<a name="step16">
### Step 16 - Create new Ingress for MLDE
</a>

Because we're using nginx, we'll need to create an ingress for MLDE.

Use this command to create the ingress:

```bash
kubectl apply -f  - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mlde-ingress
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
            name: determined-master-service-determinedai
            port:
              number: 8080
EOF
```

Then run `kubectl get ingress` and make sure the ingress is being listed with a hostname (ADDRESS) before continuing. It might take a minute for the hostname to get assigned.

Similar to the steps taken for MLDM, these commands will retrieve the load balancer address and create a URL we can use to access MLDE:

```bash
export MLDE_HOST=$(kubectl get ingress mlde-ingress --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export MLDE_URL="http://${MLDE_HOST}:80"

echo $MLDE_URL

export DET_MASTER=${MLDE_HOST}:80
```

With the `DET_MASTER` environment variable set, you can run `det e list`, which should return an empty list. If you get an error message, check the MLDE pod and service for errors.

You should also be able to access the MLDE UI using the URL printed on the terminal. Login as user **admin** (leave password field empty). Once logged in, check the **Cluster** page and make sure the GPU resources are showing up:


![alt text][aws_mlde_01_ui]

[aws_mlde_01_ui]: images/aws_mlde_01_ui.png "MLDE UI - Clusters"



&nbsp;
<a name="step17">
### Step 17 - Deploy KServe
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
<a name="step18">
### Step 18 - (Optional) Test Components
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


![alt text][aws_mldm_02_test_pipeline]

[aws_mldm_02_test_pipeline]: images/aws_mldm_02_test_pipeline.png "MLDM Test Pipeline"


&nbsp;

You should also be able to see the *chunks* in the storage bucket. This confirms that MLDM is able to connect to the bucket.


![alt text][aws_mldm_03_chunks]

[aws_mldm_03_chunks]: images/aws_mldm_03_chunks.png "MLDM Storage Bucket"


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
  slots_per_trial: 4
EOF
```

PS: We need to modify this file because our GPU node pool is configured with taints that will reject workloads. In this case, we're setting a toleration for this taint. We're also configuring the experiment to use 4 GPUs. And we're reducing the number of epochs to keep the training time short.

Use this command to run the experiment:

```bash
det experiment create -f ./examples/computer_vision/cifar10_pytorch/const.yaml ./examples/computer_vision/cifar10_pytorch
```
 If this command fails, make sure the `DET_MASTER` environment variable is set. For the first execution, the client might time out while it's waiting for the image to be pulled from docker hub. It does not mean the experiment has failed; you can still check the UI or use `det e list` to see the current status of this experiment.


&nbsp;

Your experiment will appear under Uncategorized (we will change that for the PDK experiments). You can track the Experiment log to see if there are any issues.


![alt text][aws_mlde_04_test_experiment]

[aws_mlde_04_test_experiment]: images/aws_mlde_04_test_experiment.png "MLDE Experiment"


&nbsp;

You can also check the MLDE bucket in S3 to see the checkpoints that were saved:


![alt text][aws_mlde_05_bucket]

[aws_mlde_05_bucket]: images/aws_mlde_05_bucket.png "MLDE Storage Bucket"

This confirms that MLDE is able to access the Storage bucket as well.


&nbsp;

Finally, go to the MLDE **Home Page** and click the **Launch JupyterLab** button. In the configuration pop-up, select the *Uncategorized* workspace, set the *Resource Pool* to **gpu-pool** (this is important, because the *default* pool has no GPUs available) and set the number of *Slots* (GPUs) to 1. Or set the number of slots to 0 and select the *default* Resource Pool to create a CPU-based notebook environment.

Click **Launch** to start the JupyterLab environment.

The first run should take about one minute to pull and run the image.


![alt text][aws_mlde_06_jupyter]

[aws_mlde_06_jupyter]: images/aws_mlde_06_jupyter.png "MLDE Launch JupyterLab"


In the new tab, make sure the *shared_fs* folder is listed. In this folder, users will be able to permanently store their model assets, notebooks and other files.

![alt text][aws_mlde_07_shared_folder]

[aws_mlde_07_shared_folder]: images/aws_mlde_07_shared_folder.png "MLDE Notebook Shared Folder"

PS: If the JupyterLab environment fails to load, it might be because the EFS volume failed to mount. Run `kubectl -n gpu-pool describe pod` against the new pod to see why the pod failed to run.


&nbsp;
<a name="step19">
### Step 19 - Prepare for PDK Setup
</a>

These next steps will help us verify that KServe is working properly, and they will also setup some pre-requisites for the PDK flow (specifically, the step where models are deployed to KServe).

A deeper explanation of the P-D-K flow is provided in the [main page](readme.md); for now, let's make sure KServe is working as expected.

Models deployed to KServe will run in pods that will be created in the `${KSERVE_MODELS_NAMESPACE}` namespace. This namespace was created by the EKS installer, as additional permissions were granted to give it access to the S3 bucket. You can confirm that the namespace and service account exist by running this command:

```bash
kubectl -n ${KSERVE_MODELS_NAMESPACE} get sa default -o yaml
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

![alt text][kserve_01_samplemodel]

[kserve_01_samplemodel]: images/kserve_01_samplemodel.png "KServe Sample Model"


Next, check the IP address for the Ingress:

```bash
kubectl get svc istio-ingressgateway -n istio-system

export INGRESS_HOST=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export INGRESS_PORT=$(kubectl -n istio-system get service istio-ingressgateway -o jsonpath='{.spec.ports[?(@.name=="http2")].port}')

export SERVICE_HOSTNAME=$(kubectl get inferenceservice sklearn-iris -n ${KSERVE_MODELS_NAMESPACE} -o jsonpath='{.status.url}' | cut -d "/" -f 3)

echo $INGRESS_HOST

echo $INGRESS_PORT

echo $SERVICE_HOSTNAME
```

Make sure the command output includes a public hostname. Fix any issues before continuing.


![alt text][aws_kserve_01_ingress]

[aws_kserve_01_ingress]: images/aws_kserve_01_ingress.png "KServe Ingress Info"


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


![alt text][aws_kserve_02_prediction]

[aws_kserve_02_prediction]: images/aws_kserve_02_prediction.png "KServe Sample Prediction"



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
  det_master: "${MLDE_HOST}:80"
  det_user: "admin"
  det_password: ""
  pac_token: ""
  pachd_lb_service_host: "${MLDM_HOST}"
  pachd_lb_service_port: "80"
  kserve_namespace: "models"
EOF
```

A more detailed explanation of these attributes:

- `det_master`: The address to the MLDE instance. Instead of using a URL, you can also point it to the service running in the default namespace (`determined-master-service-determinedai`).
- `det_user`: MLDE user that will create experiments and pull models.
- `det_password`: Password to the user specified above
- `pac_token`: For the Enterprise version of Pachyderm, create an authentication token for a user. Otherwise, if you use the community edition, leave it blank.
- `kserve_namespace`: Namespace where MLDM will deploy models to

&nbsp;

This secret needs to be created in the MLDM namespace, as it will be used by the pipelines (that will then map the variables to the MLDE experiment):

```bash
kubectl -n ${MLDM_NAMESPACE} apply -f pipeline-secret.yaml
```

Next, the MLDM Worker service account (which will be used to run the pods that contain the pipeline code) needs to gain access to the `${KSERVE_MODELS_NAMESPACE}` namespace, or it won't be able to deploy models there.

Run this command to create the Cluster Role and Cluster Role Binding:

```bash
kubectl apply -f  - <<EOF
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


Finally, create dummy credentials to allow access to the MLDM repo through the S3 protocol.

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
<a name="step19b">
### Step 19b - [Optional] Configure KServe UI
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
export KSERVE_UI_HOST=$(kubectl -n ${KSERVE_MODELS_NAMESPACE} get svc model-webapp-service --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export KSERVE_UI_URL="http://${KSERVE_UI_HOST}:8080"

echo $KSERVE_UI_URL
```

You can access the URL to see the deployed model (make sure to select the correct namespace).


![alt text][aws_kserve_03_ui]

[aws_kserve_03_ui]: images/aws_kserve_03_ui.png "KServe UI"






&nbsp;
<a name="step20">
### Step 20 - Prepare Docker and ECR to manage images
</a>

For this step, make sure Docker Desktop is running.

Since each PDK use case will likely need to use specific images, we'll setup ECR as the registry for these images.

First, we'll create a repository to make sure the command line works. You can skip this if you want and get the URI directly from the AWS Console.

```bash
aws ecr create-repository --repository-name=${NAME} --region ${AWS_REGION}
```

Next, retrieve the repository Uri:
```bash
export ECR_URI=$(aws ecr describe-repositories --repository-names "${NAME}" --query 'repositories[0]."repositoryUri"' --output text | sed 's:/[^/]*$::')

echo $ECR_URI
```

Use this command to login to ECR:

```bash
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}
```

The next commands can be used to pull the busybox image (as an example) and push it to ECR. By default, ECR will not allow an image to be pushed, unless there is an existing repository with the same name. Because of that, we will create the repository, tag and push the image.

```bash
docker pull busybox:latest

aws ecr create-repository --repository-name=${NAME}/busybox --region ${AWS_REGION}

docker tag busybox:latest ${ECR_URI}/${NAME}/busybox

docker push ${ECR_URI}/${NAME}/busybox
```

Check the output for error messages. An EOF message means the image failed to be uploaded. In this case, retry the push command.

You can check the ECR UI to make sure the new image is there:


![alt text][aws_ecr_01_busybox]

[aws_ecr_01_busybox]: images/aws_ecr_01_busybox.png "Busybox image pushed to ECR"



&nbsp;
<a name="step21">
### Step 21 - Save data to Config Map
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
  region: "${AWS_REGION}"
  mldm_namespace: "${MLDM_NAMESPACE}"
  mldm_bucket_name: "${MLDM_BUCKET_NAME}"
  mldm_host: "${MLDM_HOST}"
  mldm_port: "80"
  mldm_url: "${MLDM_URL}"
  mldm_pipeline_secret: "pipeline-secret"
  mlde_bucket_name: "${MLDE_BUCKET_NAME}"
  mlde_host: "${MLDE_HOST}"
  mlde_port: "80"
  mlde_url: "${MLDE_URL}"
  kserve_ui_url: "${KSERVE_UI_URL}"
  kserve_model_bucket_name: "${MODEL_ASSETS_BUCKET_NAME}"
  kserve_model_namespace: "${KSERVE_MODELS_NAMESPACE}"
  kserve_ingress_host: "${INGRESS_HOST}"
  kserve_ingress_port: "${INGRESS_PORT}"
  db_connection_string: "${RDS_CONNECTION_URL}"
  registry_uri: "${ECR_URI}/${NAME}"
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
## AWS - Useful Commands
</a>

### Creating folders in the S3 bucket

You can create the folders through the AWS Console UI, or use the following commands:

```bash
aws s3api put-object --bucket ${MODEL_ASSETS_BUCKET_NAME} --key dogs-and-cats/

aws s3api put-object --bucket ${MODEL_ASSETS_BUCKET_NAME} --key dogs-and-cats/config/

aws s3api put-object --bucket ${MODEL_ASSETS_BUCKET_NAME} --key dogs-and-cats/model-store/
```




&nbsp;

---

&nbsp;

The installation steps are now completed. At this time, you have a working cluster, with MLDM, MLDE and KServe deployed.

Next, return to [the main page](README.md) to go through the steps to prepare and deploy the PDK flow for the dogs-and-cats demo.

<br/><br/>
