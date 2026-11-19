# SmartTITU Assistant UAT 环境部署

UAT 环境位于 火山云 平台 华南1(广州) https://console.volcengine.com/vke/region:vke+cn-guangzhou/cluster?projectName=default

k8s 集群名称 titu-hub-poc   https://console.volcengine.com/vke/region:vke+cn-guangzhou/cluster/cd83ffno1tj6gpn2mf040?




Postgres 数据库使用已有的实例 https://console.volcengine.com/dbw/region:dbw+cn-guangzhou/observation?dsType=Postgres&instanceId=postgres-909ea8174503&regionId=cn-guangzhou&tab=dbCopilot

需要创建 智能客服应用专用 数据库和账号


Milvus 需要自己在 k8s 集群 titu-hub-poc 上自行部署 ，创建专属命名空间 milvus-test 依赖 的前置条件 storageless  ebs-ssd

kubectl port-forward --address 0.0.0.0 service/milvus-26-milvus 19530:19530 -n milvus-test


智能客服应用 smarttitu-assistant 部署的 namespace 为 app-zone,  依赖的前置条件 storageless  ebs-ssd



火山云 UAT 容器镜像仓库为  https://console.volcengine.com/cr/region:cr+cn-guangzhou/instance/ctt-repository/repositories?filterProject=default&filterNamespace=smarttitu-assistant

部署之前需要打包上传服务需要的所有镜像到上述镜像仓库


python 02_milvus.py --collection smarttitu_knowledge_1299041d3ee49db9 --dimension 1024




kubectl port-forward --address 0.0.0.0 service/titu-assistant 80:8088 -n app-zone




http://titu-assistant.app-zone.svc.cluster.local:80/smart-bot/iframe-anonymous.js
