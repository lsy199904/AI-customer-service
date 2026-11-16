生产入口：`sh scripts/production.sh deploy`。

通过`.env`生成ConfigMap、Secret、单副本Deployment、ClusterIP Service、PVC及一次性初始化Job。`render`可生成不含密钥的审阅清单；实际部署请使用脚本，保证先初始化后启动。完整说明见 [部署说明](../../docs/部署说明.md)。
