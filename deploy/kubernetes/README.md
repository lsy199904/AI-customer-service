生产入口：`sh scripts/production.sh deploy`。

通过`.env`生成ConfigMap、Secret、单副本Deployment、ClusterIP Service、PVC及一次性初始化Job。`render`可生成不含密钥的审阅清单；实际部署请使用脚本，保证先初始化后启动。完整说明见 [部署说明](../../docs/部署说明.md)。

手写Kubernetes YAML时，使用[应用环境变量模板](app.env.example)：逐项填写空白配置，将密钥放入Secret，其余参数放入ConfigMap，再注入App和初始化Job。无需使用自动化部署参数；填写真实凭证后的文件不提交Git。
