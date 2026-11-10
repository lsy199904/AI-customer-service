> 路径更新：当前对外请求统一加 `/smart-bot`，以《统一路径前缀接入.md》为准。以下历史路径说明用于理解原有协议。

# 匿名iframe独立入口

## 版本与范围

分支 v3-anonymous-iframe，基于服务器已确认的027c363。保留原/chatbot、/iframe.js及父页面凭证协议；知识库、检索和模型不变。已合入v3-answer-image-focus的既有回答聚焦与配图约束，以及其已有的基础夜间压测工具；本次不额外调整这些逻辑。未合入后来v3的100并发增强批次。

新增/chatbot/anonymous和可选/iframe-anonymous.js；原demo页面独立保留。匿名开关默认关闭，必须显式启用。原/chatbot继续使用原签发凭证的方式。

## 双方对接

客服方提供正式HTTPS链接 https://客服域名/chatbot/anonymous。平台方提供测试/生产完整来源（协议、域名、必要端口），供配置FRAME_ORIGINS，然后直接嵌入：

```html
<iframe src="https://客服域名/chatbot/anonymous"
        title="智能客服"
        style="width:414px;height:680px;border:0;"></iframe>
```

页面也可以用自己的按钮控制iframe显示隐藏。若需客服自带浮窗，改用：

```html
<script src="https://客服域名/iframe-anonymous.js"></script>
```

以上二选一，不同时加载。匿名悬浮脚本已采用Demo同款support-robot-b.png，桌面88×80、展开后56×52、手机62×56，并保留浮动动画及减少动态效果偏好；通过Shadow DOM隔离平台样式。匿名入口不要求平台传用户ID、Cookie、Token或签名密钥。来源白名单是嵌入许可，不是用户身份验证，不代表公共入口不能被直接打开。保留的原凭证脚本仍为/iframe.js，两套脚本分别提供SmartTITUAnonymousEmbed和SmartTITUEmbed控制对象。

## 身份和历史

匿名接口 POST /widget/anonymous-auth（JSON请求体{}）生成服务器随机UUID，签名Cookie与短期Bearer。前端不接受由父页面或URL指定的访客ID；会话读写删除均使用既有企业和用户归属校验，不以session_id本身授权。匿名身份与demo身份及正式平台身份分离。

Cookie有效期30天，API凭证1小时，聊天记录仍按现有7天保留。开启后匿名凭证可在关闭demo入口时独立工作。禁用匿名入口会阻止新签发，并拒绝现有匿名凭证。签名密钥只能在客服后端保存。

HTTPS使用HttpOnly、Secure、SameSite=None并附加Partitioned，以支持允许此行为的跨站浏览器；HTTP内网测试使用SameSite=Lax。生产HTTPS在代理终止时必须设置ANONYMOUS_COOKIE_SECURE=true，不信任任意客户端传来的X-Forwarded-Proto。

支持分区Cookie时，同一浏览器在不同顶层网站可形成不同访客身份。部分浏览器禁止第三方Cookie时，当前iframe仅在内存中保持Bearer并用于续期，不回退至公共身份；刷新或重建iframe后可能成为新访客，无法承诺恢复原历史。部署前应验证目标浏览器；如要求稳定历史，可考虑同源部署或代理。换网络通常不改变身份，多人共用同一浏览器配置可能共享历史。

匿名没有真实企业信息，本次保留现有限流：所有匿名访客共用独立匿名租户的20条/分钟额度，而不是每人20条；会话数据仍按访客独立隔离。生产放量前应另行确定匿名入口的流量配额和防滥用方式，本次不擅自修改限流。

## 启用和部署

更新前保存当前代码位置，工作区应干净。独立分支不覆盖v3。

```bash
cd ~/ai_customer/ai_customer_v3

git rev-parse HEAD > .git/before-anonymous-iframe &&
git fetch origin refs/heads/v3-anonymous-iframe:refs/remotes/origin/v3-anonymous-iframe &&
git switch -c v3-anonymous-iframe --track origin/v3-anonymous-iframe &&
sh scripts/v3.sh anonymous enable &&
sh scripts/v3.sh start &&
sh scripts/v3.sh check
```

这是首次创建本地分支的命令。若分支已存在，切换该分支后按显式refspec fetch并fast-forward更新；不要reset --hard。

直接浏览器测试：http://服务器地址:8200/chatbot/anonymous。与原8200服务共用同一应用实例，启动会有短暂重建；不是额外开启端口。无需重新入库、无需重建镜像，没有新增依赖。默认关闭，需要enable后才能匿名使用。

正式域名确定后配置平台白名单（替换示例域名）：

```bash
sh scripts/v3.sh anonymous enable --origin https://platform.example.com --https-cookie &&
sh scripts/v3.sh start
```

配置脚本只更新匿名开关、显式请求的Cookie选项和白名单追加，保留原密钥、模型和登录配置，并在backups/anonymous-时间/备份.env，权限600。代理还需保证SSE不缓存、支持长连接；公开地址应HTTPS。原/chatbot凭证入口保持不变。

## 停用与回退

只关闭匿名入口，保留当前代码和原凭证接口：

```bash
sh scripts/v3.sh anonymous disable && sh scripts/v3.sh start
```

回退至更新前记录的代码版本：

```bash
git switch --detach "$(cat .git/before-anonymous-iframe)" &&
sh scripts/v3.sh start &&
sh scripts/v3.sh check
```

.env备份中包含签名密钥，不可上传Git或提供给浏览器。不同代码版本可能对已有短期凭证有不同开关处理，退回旧代码不等于撤销所有已签发凭证；不应为此随意轮换正式密钥。

## 验证

合并既有优化后完整Python/Node回归398项，390通过、8跳过（依赖外部环境的测试）。原凭证桥接、演示入口、真实SSE增量、历史一致性及匿名跨会话读写删除拒绝均在回归内。匿名JS测试还覆盖无父页面脚本、并行取凭证去重、内存Bearer续期、关闭入口及错误处理。

真实Chrome临时本地环境验证：跨端口同站iframe，无父页面脚本，提交问候成功；两个独立浏览器上下文历史隔离、交叉读取返回404、刷新后恢复自己的历史。HTTPS Cookie属性由接口测试验证；尚未在实际生产域名、跨站代理和所有目标浏览器上验证，不承诺所有浏览器允许第三方Cookie。未执行GPU性能压测或服务器部署。

机器人外观更新验证：21项相关自动回归通过；真实Chrome检查桌面/手机尺寸、同图资源、平台CSS隔离、展开关闭、匿名连接及销毁。此更新不改后端或访客凭证。

匿名悬浮效果预览页：/widget/anonymous-demo。此页面加载同一个/iframe-anonymous.js，无需平台Token接口；要求已启用匿名入口。同源预览不代表生产跨站Cookie已验证。
