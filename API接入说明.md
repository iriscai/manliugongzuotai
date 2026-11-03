# 中转API接入来源与使用

参考项目：`D:\BIGDATA\CODES\PyCharmFiles\大富豪\FunnyComicTitleGenerator`

对应源码：`src/comic_title_tool/core.py`中的`GPTClient`、`completion_url`、`models_url`和`fetch_available_models`。

移植内容包括Chat Completions流式生文、system/user消息、Temperature、多Key轮询、Bearer头、原User-Agent、流式文本组合、分段超时、连接测试和模型列表读取。业务提示词使用本工作台的独立规则，原项目不作修改。

本工作台的适配部分包括Windows DPAPI加密保存Key、不回显密钥、按JSON Schema校验模型输出、保存隐藏密钥后的返回记录，以及现有任务的暂停、续跑、字数和分镜检查。证书验证默认开启，前台提供原项目的兼容开关。

使用入口为“执行设置 → 中转API”。可从原项目配置导入，也可手动填写。保存后下一轮任务使用新配置；已启动任务继续沿用快照。本机Codex执行入口保留。

连接测试会逐个Key发送简短请求；拉取模型列表调用对应/models接口。保存设置不调用模型。本工作台不把执行结果自动写回SKILL。

源码构建使用`build_backend.py`，该脚本同时打包HTTP客户端依赖和当前Python所需证书资源。原项目的明文配置文件不复制进发布包。
