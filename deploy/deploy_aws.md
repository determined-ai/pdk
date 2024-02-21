![alt text][hpe_logo]

[hpe_logo]: images/hpe_logo.png "HPE Logo"


# PDK - Pachyderm | Determined | KServe
## Deployment Guide for AWS
<b>Date/Revision:</b> February 23, 2024


This guide will walk you through the steps of deploying the PDK components to AWS.


## Reference Architecture
The installation will be performed on the following hardware:

- 3x m5.2xlarge CPU-based nodes (8 vCPUs, 32GB RAM, 1000GB HDD)
- 1x g4dn.metal GPU-based nodes (8 NVIDIA-T4, 96 vCPUs, 384GB RAM, 1000GB HDD)

The 3 CPU-based nodes will be used to run the services for all 3 products, and the MLDM pipelines. The GPU-based node will be used to run MLDE experiments.

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
  - aws cli (make sure it's initialized and logged in; basic client configuration is out of scope for this doc)
  - eksctl (to create the EKS cluster)
  - helm
  - jq
  - openssl (to generate a random password for the MLDE admin)
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

[10 - Deploy nginx for MLDE](#step10)

[11 - Deploy KServe](#step11)

[12 - Create configuration .yaml file for MLDM and MLDE](#step12)

[13 - Install MLDM and MLDE using Helm](#step13)

[14 - Create new Ingress for MLDE](#step14)

[15 - Retrieve MLDM and MLDE hostnames and configure command line clients](#step15)

[16 - (Optional) Test Components](#step16)

[17 - Prepare for PDK Setup](#step17)

[18 - [Optional] Configure KServe UI](#step18)

[19 - [Optional] Prepare Docker and ECR to manage images](#step19)

[20 - Save data to Config Map](#step20)

[99 - Cleanup Commands](#step99)

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

**Important:** The script will generate a default password for the MLDE Admin. You can replace it with a password of your choice. The admin password will be stored in a secret and can be retrieved through the `kubectl` command line.


```bash
# MODIFY THESE VARIABLES
export NAME="your-name-pdk"
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

# Generate admin password for MLDE (or set your own password)
export ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -dc A-Za-z0-9 | head -c16)

# Optionally, set a different password for the database:
export RDS_ADMIN_PASSWORD="${ADMIN_PASSWORD}"
```



&nbsp;
<a name="step2">
### Step 2 - Test the pre-req client applications
</a>

Make sure all these commands return successfully. If one of them fails, fix the issue before continuing.

Install MLDE client:
```bash
pip install determined
```

Install MLDM client (MacOS):
```bash
brew tap pachyderm/tap && brew install pachyderm/tap/pachctl@2.8  
```

Check versions:
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
  version: "1.27"

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
      namespace: "default"
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
      namespace: "default"
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
    minSize: 1
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

You can inspect these new roles to see the permissions that are being granted. The Trust relationship tab will show which Kubernetes service accounts are allowed to assume this role at runtime. In this case, we can see that the **pachyderm** service account in the default namespace is able to assume this role, which grants permissions on the S3 bucket:

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

This will take a couple of minutes to take effect. Run a `kubectl get nodes` and then a `kubectl describe node <node_name>` in the GPU node. Look for the Allocatable section; if you don't see a `nvidia.com/gpu: 8` entry in that list, wait a few seconds and check again. Do not continue until the GPUs are being listed as allocatable.

You can also use this command to list allocatable GPUs per node:

```bash
kubectl describe nodes  |  tr -d '\000' | sed -n -e '/^Name/,/Roles/p' -e '/^Capacity/,/Allocatable/p' -e '/^Allocated resources/,/Events/p'  | grep -e Name  -e  nvidia.com  | perl -pe 's/\n//'  |  perl -pe 's/Name:/\n/g' | sed 's/nvidia.com\/gpu:\?//g'  | sed '1s/^/Node Available(GPUs)  Used(GPUs)/' | sed 's/$/ 0 0 0/'  | awk '{print $1, $2, $3}'  | column -t
```


For the MLDE installation, we'll configure the GPU nodes to be in a separate Resource Pool. This requires a new namespace for the GPU nodes, as experiments will run as pods in that namespace (that will then be bound to the GPU nodes). Because the EKS creation template assigned the necessary permissions to access the S3 bucket, the `gpu-pool` namespace was automatically created, along with the service account.

You can check the service account by running `kubectl -n gpu-pool get sa`.

&nbsp;

**Important**: Now that the GPUs are being listed, you can downscale the GPU node group to a minimum of zero nodes; this will ensure that you are not paying for the GPUs unless there are active workloads using them.

To reconfigure the cluster, go to the EKS page for your cluster on the AWS UI, click on the **Compute** tab, select the **managed-gpu-nodes** node group and click on the Edit button.

![alt text][aws_eks_06_gpunodegroup]

[aws_eks_06_gpunodegroup]: images/aws_eks_06_gpunodegroup.png "EKS - Compute - Node Groups"


In the next screen, set the **Desired** and **Minimum** to zero. Scroll down and click **Save changes**.


![alt text][aws_eks_07_nodegroupsize]

[aws_eks_07_nodegroupsize]: images/aws_eks_07_nodegroupsize.png "Node Group - Desired and Minimum size"

It should take a few minutes for the cluster to scale down. Nodes will be added automatically when the cluster requires GPU for a task (MLDE experiments, notebooks, etc).


&nbsp;
<a name="step7">
### Step 7 - Configure Shared Storage and the Storage Classes
</a>

MLDE offers a hosted Jupyter Lab environment, where users can create and run notebooks. This environment needs persistent storage, in order to save user files. This persistent storage must be mounted as a shared folder. In this step, we will configure the necessary components to enable this capability.

First, we need to create a security group that allows inbound NFS access to the EFS volume. Execute these commands to collect the necessary data and create the security group.

```bash
export AWS_VPC_ID=$(aws eks describe-cluster --name ${CLUSTER_NAME} --query 'cluster.resourcesVpcConfig.vpcId' --output text)
echo ${AWS_VPC_ID}

export AWS_VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids ${AWS_VPC_ID} --query 'Vpcs[].CidrBlock' --output text)

aws ec2 create-security-group --description ${CLUSTER_NAME}-sg-efs --group-name ${CLUSTER_NAME}-sg-efs --vpc-id ${AWS_VPC_ID}

export SEC_GROUP_ID=$(aws ec2 describe-security-groups \
  --filters Name=vpc-id,Values=${AWS_VPC_ID} Name=group-name,Values=${CLUSTER_NAME}-sg-efs\
  --query 'SecurityGroups[0].GroupId' --output text)
echo ${SEC_GROUP_ID}

aws ec2 authorize-security-group-ingress --group-id ${SEC_GROUP_ID} --protocol tcp --port 2049 --cidr ${AWS_VPC_CIDR}
```

**IMPORTANT**: This Security group will authorize IPs inside the CIDR range for your VPC. If you have multiple CIDR ranges, you will need to run the `aws ec2 authorize-security-group-ingress` command for every CIDR range, or you risk your nodes not being included in this rule, which will cause the volume to fail to provision. You can use this command to list all CIDR ranges used by your VPC:
```bash
aws ec2 describe-vpcs --vpc-ids ${AWS_VPC_ID} --query 'Vpcs[].CidrBlockAssociationSet'
```
If you see more than one result in this command, run the `authorize-security-group-ingress` for each range in the response.

Example:

```bash
aws ec2 describe-vpcs --vpc-ids ${AWS_VPC_ID} --query 'Vpcs[].CidrBlockAssociationSet'
[
    [
        {
            "AssociationId": "vpc-cidr-assoc-0afb113a774eb5cbc",
            "CidrBlock": "10.0.0.0/24",
            "CidrBlockState": {
                "State": "associated"
            }
        },
        {
            "AssociationId": "vpc-cidr-assoc-023247e7eed42e6ed",
            "CidrBlock": "100.64.0.0/16",
            "CidrBlockState": {
                "State": "associated"
            }
        }
    ]
]

# 10.0.0.0/24 was already authorized by the previous command

export AWS_VPC_CIDR="100.64.0.0/16"

aws ec2 authorize-security-group-ingress --group-id ${SEC_GROUP_ID} --protocol tcp --port 2049 --cidr ${AWS_VPC_CIDR}


```

&nbsp;

Next, create the EFS volume:
```bash
aws efs create-file-system --creation-token ${CLUSTER_NAME}-efs --tags Key=Name,Value=${CLUSTER_NAME}-efs

export EFS_ID=$(aws efs describe-file-systems --creation-token ${CLUSTER_NAME}-efs \
  --query 'FileSystems[0].FileSystemId' --output text)

echo ${EFS_ID}
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
volumeBindingMode: WaitForFirstConsumer
allowedTopologies:
- matchLabelExpressions:
  - key: failure-domain.beta.kubernetes.io/zone
    values:
    - ${AWS_AVAILABILITY_ZONE_1}
    - ${AWS_AVAILABILITY_ZONE_2}
    - ${AWS_AVAILABILITY_ZONE_3}    
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

Now, create two Persistent Volumes and two Persistent Volume Claims, which will be associated with the file system we just created. We'll create one PV and one PVC in each namespace that can run MLDE notebooks (*default* and *gpu-pool*). The *default* namespace is created with the Kubernetes cluster, and the EKS installer already created the *gpu-pool* namespace as well (since it needed to grant bucket permissions to it). Run `kubectl get ns` to confirm that the *gpu-pool* namespace exists.

PS: We're setting it for 200GB, but you can modify the size as needed.

Run this command to create the first PV and PVC:
```bash
kubectl apply -f  - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: pdk-pv
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
  name: pdk-pvc
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
  name: pdk-pv-gpu
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
  name: pdk-pvc
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
        - image: k8s.gcr.io/autoscaling/cluster-autoscaler:v1.26.2
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
    --subnet-ids "${AWS_VPC_SUBNET_1_ID}" "${AWS_VPC_SUBNET_2_ID}" "${AWS_VPC_SUBNET_3_ID}" \
    --output text
```

Use the following command to provision a cloud Postgres database. Leave the `--publicly-accessible` flag if you want to access the database from an external client (like DBeaver, or a custom app).

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
    --publicly-accessible \
    --output text
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

At this time, if you've set the `--publicly-accessible` flag, you can connect using your external client:


![alt text][aws_rds_01_dbeaver]

[aws_rds_01_dbeaver]: images/aws_rds_01_dbeaver.png "External Postgres client"


The next step is to setup the 3 databases that will be used by PDK. Since the AWS client doesn't have the ability to create databases inside an instance, there are a few options that could be considered:
- Connect the database to an EC2 instance
- Use the external client (DBeaver in this case)
- Use the postgres `psql` command line utility (`psql -h ${RDS_CONNECTION_URL} postgres postgres`)
- Create a pod with psql and connect to the instance

You will also need the password, which can be obtained by running this command:

```bash
echo $RDS_ADMIN_PASSWORD
```

To create the databases using the psql pod, use these commands:


```bash
kubectl run psql -it --rm=true --image=postgres:13 --command -- psql -h ${RDS_CONNECTION_URL} -U postgres postgres

# The prompt will freeze as it loads the pod. Wait for the message "If you don't see a command prompt, try pressing enter".
# Then, type (or paste) the password and press enter.

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
### Step 10 - Deploy nginx for MLDE
</a>

Nginx will be configured to listen on port 80 (instead of the default 8080 used by MLDE).

```bash

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx

helm repo update

helm install -n ingress-system --create-namespace ingress-nginx ingress-nginx/ingress-nginx

```

PS: This could take a couple of minutes. Run `kubectl -n ingress-system get svc` and make sure that the External IP column is showing a value. If the field is empty (or showing Pending), investigate and fix it before continuing.




&nbsp;
<a name="step11">
### Step 11 - Deploy KServe
</a>

KServe is a standard Model Inference Platform on Kubernetes, built for highly scalable use cases. It provides performant, standardized inference protocol across ML frameworks, including PyTorch, TensorFlow and Keras.
Additionally, KServe provides features such as automatic scaling, monitoring, and logging, making it easy to manage deployed models in production. Advanced features, such as canary rollouts, experiments, ensembles and transformers are also available.
For more information on KServe, please visit [the official KServe documentation](https://kserve.github.io/website/0.9/).


Installation of KServe is very straightforward, because we are using the Quick Start. This is naturally only an option for test or demo environments;

```bash
curl -s "https://raw.githubusercontent.com/kserve/kserve/master/hack/quick_install.sh" | bash
```

After running this command, wait about 10 minutes for all the services to be properly initialized.






&nbsp;
<a name="step12">
### Step 12 - Create configuration .yaml file for MLDM and MLDE
</a>

As of MLDM version 2.8.2, a single Helm chart can be used to deploy both MLDM and MDLE.

Because we're using the AWS buckets, there are 2 service accounts that will need access to S3: the main MLDM service account and the `worker` MLDM service account, which runs the pipeline code.

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
cat <<EOF > helm_values.yaml
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

determined:
  enabled: true
  detVersion: "0.28.1"
  imageRegistry: determinedai
  enterpriseEdition: false
  imagePullSecretName:
  createNonNamespacedObjects: true
  masterPort: 8080
  useNodePortForMaster: true
  defaultPassword: ${ADMIN_PASSWORD}
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
  maxSlotsPerPod: 8
  masterCpuRequest: "4"
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
  defaultAuxResourcePool: default
  defaultComputeResourcePool: gpu-pool
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
                  claimName: pdk-pvc
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
                  claimName: pdk-pvc
            tolerations:
              - key: "nvidia.com/gpu"
                operator: "Equal"
                value: "present"
                effect: "NoSchedule"
EOF
```


&nbsp;
<a name="step13">
### Step 13 - Install MLDM and MLDE using Helm
</a>

First, download the charts for MLDM:

```bash
helm repo add pachyderm https://helm.pachyderm.com

helm repo update
```

Then run the installer, referencing the .yaml file you just created:

```bash
helm install pachyderm -f ./helm_values.yaml pachyderm/pachyderm
```

Give it a couple of minutes for all the services to be up and running. Both products will be deployed to the `default` namespace. You can run `kubectl get pods` to see if any pods failed or are stuck. Wait until all pods are running before continuing.


&nbsp;
<a name="step14">
### Step 14 - Create new Ingress for MLDE
</a>

Because we're using nginx, we'll need to create an ingress for MLDE.

Use this command to create the ingress:

```bash
kubectl apply -f  - <<EOF
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

Then run `kubectl get ingress` and make sure the ingress is being listed with a hostname (ADDRESS) before continuing. It might take a minute for the hostname (load balancer) to get assigned.


&nbsp;
<a name="step15">
### Step 15 - Retrieve MLDM and MLDE hostnames and configure command line clients
</a>

In this step, we'll configure the `pachctl` and `det` clients. This will be important later, as we create the project, repo and pipeline for the PDK environment.

```bash
export MLDM_HOST=$(kubectl get svc pachyderm-proxy --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export MLDM_URL="http://${MLDM_HOST}:80"

echo $MLDM_URL

pachctl connect ${MLDM_URL}

pachctl config set active-context ${MLDM_URL}
```

PS: You need a working URL to continue.

At this time, you should be able to access the MLDM UI using the URL that was printed in the terminal:


![alt text][aws_mldm_01_ui]

[aws_mldm_01_ui]: images/aws_mldm_01_ui.png "MLDM Dashboard"

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

Similar to the steps taken for MLDM, these commands will retrieve the load balancer address and create a URL we can use to access MLDE:

```bash
export MLDE_HOST=$(kubectl get ingress mlde-ingress --output jsonpath='{.status.loadBalancer.ingress[0].hostname}')

export MLDE_URL="http://${MLDE_HOST}:80"

echo $MLDE_URL

export DET_MASTER=${MLDE_HOST}:80

echo ${ADMIN_PASSWORD}

det u login admin
```
(use the password that was displayed in the previous command)

Once logged in, you can run `det e list`, which should return an empty list. If you get an error message, check the MLDE pod and service for errors.

You should also be able to access the MLDE UI using the URL printed on the terminal. Login as user **admin** (leave password field empty). Once logged in, check the **Cluster** page. The 'No connected agents' message means that the cluster was downscaled to 0 GPU nodes:


![alt text][aws_mlde_01_ui]

[aws_mlde_01_ui]: images/aws_mlde_01_ui.png "MLDE UI - Clusters"


As mentioned before, a new GPU node will be automatically provisioned when MLDE receives a workload to process.


&nbsp;
<a name="step16">
### Step 16 - (Optional) Test Components
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

PS: If you used the default image size for the CPU nodes (in the _eks-config.yaml_ file), the new pipelines may fail at first due to lack of available CPUs. In this case, the autoscaler should automatically add a new node to the CPU node group. Once the new CPUs are available, the pipeline will start automatically.

At this time, you should see the OpenCV project and pipeline in the MLDM UI:


![alt text][aws_mldm_02_test_pipeline]

[aws_mldm_02_test_pipeline]: images/aws_mldm_02_test_pipeline.png "MLDM Test Pipeline"

You can also run `kubectl get pods` to confirm that none of the `opencv` pods are running (since the pipelines have finished running).
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
 If this command fails, make sure the `DET_MASTER` environment variable is set. For the first execution, we must wait for the autoscaler to provision a GPU node in the cluster. The client will time out while it's waiting for the GPU (if there is an active GPU, the client can timeout while it's waiting for the experiment image to be pulled). It does not mean the experiment has failed; you can still check the UI or use `det e list` to see the current status of this experiment.


&nbsp;

Your experiment will appear under Uncategorized (we will change that for the PDK experiments). You can track the Experiment log to see if there are any issues.


![alt text][aws_mlde_04_test_experiment]

[aws_mlde_04_test_experiment]: images/aws_mlde_04_test_experiment.png "MLDE Experiment"


&nbsp;

You can also check the MLDE bucket in S3 to see the checkpoint that was saved:


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

When you are done testing the notebook, kill the task (in the Tasks page) to release the GPU.


&nbsp;
<a name="step17">
### Step 17 - Prepare for PDK Setup
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
curl -v \
-H "Content-Type: application/json" \
-H "Host: ${SERVICE_HOSTNAME}" \
http://${INGRESS_HOST}:${INGRESS_PORT}/v1/models/sklearn-iris:predict \
-d @./iris-input.json
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
  namespace: default
stringData:
  det_master: "${MLDE_HOST}:80"
  det_user: "admin"
  det_password: "${ADMIN_PASSWORD}"
  pac_token: ""
  pachd_lb_service_host: "${MLDM_HOST}"
  pachd_lb_service_port: "80"
  kserve_namespace: "${KSERVE_MODELS_NAMESPACE}"
EOF
```

A more detailed explanation of these attributes:

- `det_master`: The address to the MLDE instance. Instead of using a URL, you can also point it to the service running in the default namespace (`determined-master-service-determinedai`).
- `det_user`: MLDE user that will create experiments and pull models.
- `det_password`: Password to the user specified above. If you're planning on changing the password, make sure to update the secret.
- `pac_token`: For the Enterprise version of Pachyderm, create an authentication token for a user. Otherwise, if you use the community edition, leave it blank.
- `kserve_namespace`: Namespace where MLDM will deploy models to

&nbsp;

This secret will be used by the pipelines, to map the variables for the MLDE experiments:

```bash
kubectl apply -f pipeline-secret.yaml
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
  namespace: default
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
    serving.kserve.io/s3-endpoint: pachd.default:30600
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
    serving.kserve.io/s3-endpoint: pachd.default:30600
    serving.kserve.io/s3-usehttps: "0"
secrets:
- name: pach-kserve-creds
EOF
```


&nbsp;
<a name="step18">
### Step 18 - [Optional] Configure KServe UI
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

It could take a few minutes for the application to be up and running.




&nbsp;
<a name="step19">
### Step 19 - [Optional] Prepare Docker and ECR to manage images
</a>

This step is only required if you are planning to create and use your own images. In this case, make sure Docker Desktop is running.

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
<a name="step20">
### Step 20 - Save data to Config Map
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
  cluster_name: "${CLUSTER_NAME}"
  rds_instance_name: "${RDS_INSTANCE_NAME}"
  rds_subnet_name: "${RDS_SUBNET_NAME}"
  mldm_bucket_name: "${MLDM_BUCKET_NAME}"
  mlde_bucket_name: "${MLDE_BUCKET_NAME}"
  model_assets_bucket_name: "${MODEL_ASSETS_BUCKET_NAME}"
  efs_id: "${EFS_ID}"
  sec_group_id: "${SEC_GROUP_ID}"
  mldm_host: "${MLDM_HOST}"
  mldm_port: "80"
  mldm_url: "${MLDM_URL}"
  mlde_host: "${MLDE_HOST}"
  mlde_port: "80"
  mlde_url: "${MLDE_URL}"
  kserve_ui_url: "${KSERVE_UI_URL}"
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
<a name="step99">
### Step 99 - Cleanup Commands
</a>

To completely delete the cluster, you can use the AWS command line utility to remove the different components that were deployed. 

To do that, we need to retrieve the variables we will need from the Config Map created in the previous step:

```bash
export AWS_REGION=$(kubectl get cm pdk-config -o=jsonpath='{.data.region}') && echo $AWS_REGION
export CLUSTER_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.cluster_name}') && echo $CLUSTER_NAME
export RDS_INSTANCE_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.rds_instance_name}') && echo $RDS_INSTANCE_NAME
export RDS_SUBNET_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.rds_subnet_name}') && echo $RDS_SUBNET_NAME
export MLDM_BUCKET_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.mldm_bucket_name}') && echo $MLDM_BUCKET_NAME
export MLDE_BUCKET_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.mlde_bucket_name}') && echo $MLDE_BUCKET_NAME
export MODEL_ASSETS_BUCKET_NAME=$(kubectl get cm pdk-config -o=jsonpath='{.data.model_assets_bucket_name}') && echo $MODEL_ASSETS_BUCKET_NAME
export EFS_ID=$(kubectl get cm pdk-config -o=jsonpath='{.data.efs_id}') && echo $EFS_ID
export SEC_GROUP_ID=$(kubectl get cm pdk-config -o=jsonpath='{.data.sec_group_id}') && echo $SEC_GROUP_ID
```

First, delete the cluster:
```bash
eksctl delete cluster --region=${AWS_REGION} --name=${CLUSTER_NAME}
```

This should take several minutes. This command will also delete: load balancers, roles, policies, OIDC provider, etc.

Next, delete the database:

```bash
aws rds delete-db-cluster --db-cluster-identifier ${RDS_INSTANCE_NAME}-cluster --skip-final-snapshot --output text
```

This should also take several minutes, as the read-only duplicates also need to be deleted. You can use the following commands to check the status of deletion (or just track through the AWS UI):

```bash
aws rds describe-db-clusters --db-cluster-identifier ${RDS_INSTANCE_NAME}-cluster --query 'DBClusters[0].Status' --output text
```
Once the state changes from `deleting` to an error message, the Subnet group can be deleted:

```bash
aws rds delete-db-subnet-group --db-subnet-group-name ${RDS_SUBNET_NAME}
```

Next, the buckets can be deleted. The `--force` parameter will instruct AWS to delete all bucket contents first.

```bash
aws s3 rb s3://${MLDM_BUCKET_NAME} --force

aws s3 rb s3://${MLDE_BUCKET_NAME} --force

aws s3 rb s3://${MODEL_ASSETS_BUCKET_NAME} --force
```

Before we can delete the EFS volume, we must delete the mount targets. There will be 3 of them. Use this command to get a list of IDs and delete all mount targets:

```bash
array=($(aws efs describe-mount-targets --file-system-id ${EFS_ID} --region ${AWS_REGION} --query 'MountTargets[].MountTargetId' --output text))
for i in "${array[@]}"; do
    aws efs delete-mount-target --mount-target-id $i --region ${AWS_REGION}
done
```

With the mount targets deleted, the EFS volume can now be removed:

```bash
aws efs delete-file-system --file-system-id ${EFS_ID} --region ${AWS_REGION}
```

Finally, delete the security group created for EFS:

```bash
aws ec2 delete-security-group --group-id ${SEC_GROUP_ID}
```



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
