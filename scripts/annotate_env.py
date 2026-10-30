"""Add Chinese parameter documentation without parsing, printing or changing values."""
from pathlib import Path
import argparse
import os
import re
import shutil
import tempfile
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
DESCRIPTIONS=dict(line.split('|',1) for line in '''AUTH_SECRET|客服身份凭证签名密钥，至少32字节；仅后端保存，变更会使旧凭证失效并改变日志匿名标识。
ANSWER_MODE|回答模式：llm调用聊天模型；extractive直接返回知识正文，用于对照排查。
RETRIEVAL_BACKEND|知识检索方式：semantic语义混合检索；lexical传统本地关键词检索。
MODEL_BASE_URL|聊天模型服务基础地址，一般以/v1结尾，不填写完整chat/completions路径。
MODEL_API_KEY|聊天模型接口访问密钥；保密，是否可使用占位值取决于模型服务鉴权。
MODEL_NAME|聊天模型名称，必须与服务端对外暴露的模型名称一致。
MODEL_HTTP_ORIGINS|允许访问的模型HTTP服务来源，逗号分隔；填写协议、主机、端口，不带接口路径。
EMBEDDING_PROVIDER|向量接口协议：ollama或openai，需与Embedding服务匹配。
EMBEDDING_URL|文本向量化接口的完整地址，用于入库和在线检索。
EMBEDDING_MODEL|Embedding模型名称，例如bge-m3:latest。
EMBEDDING_API_KEY|Embedding接口访问密钥；无鉴权时可按服务要求留空。
EMBEDDING_REVISION|Embedding权重或处理方式版本；变化后需更新并执行ingest --rebuild。
RERANK_ENABLED|是否启用候选重排：true启用，false关闭；关闭后Rerank门槛不参与筛选。
RERANK_URL|重排接口完整地址，例如/v1/rerank。
RERANK_MODEL|重排模型名称，必须与重排服务一致。
RERANK_API_KEY|重排接口访问密钥，无鉴权时可按服务要求留空。
SEMANTIC_MIN_SIMILARITY|向量召回相似度门槛，默认0.75；不等于回答准确率。
RETRIEVAL_MIN_SIMILARITY|传统lexical检索的匹配门槛，代码默认0.14；不是语义检索的0.75门槛。
RERANK_MIN_SCORE|启用重排时的最低得分门槛，默认0.6；低于此值的候选被过滤。
RAG_TOP_K|每路召回上限，默认12；两路融合去重后最多为该值的2倍。
RAG_CONTEXT_K|交给回答模型的知识片段上限，默认3；不保证每次取满，不能大于RAG_TOP_K。
FRAME_ORIGINS|允许嵌入客服iframe的父页面来源，逗号分隔，准确到协议、主机与端口。
CORS_ORIGINS|允许跨域调用客服接口的浏览器页面来源，逗号分隔；与iframe来源限制用途不同。
SUPPORT_QR_URL|人工联系企业微信二维码地址，未配置时留空；不会自动连接真人客服。
SOURCE_BASE_URL|历史配置：来源文档基础URL；当前来源面板已取消原文下载与外链入口。
HOST|客服监听地址：127.0.0.1仅本机访问；0.0.0.0监听全部网卡，访问范围由网络策略决定。
PORT|客服HTTP监听端口，主版本通常8000，独立v2部署通常8100。
DATABASE_URL|客服PostgreSQL连接串，包含地址、端口、数据库与账号密码；保密。
DATABASE_PATH|未使用PostgreSQL时的本地SQLite聊天数据库路径。
VECTOR_BACKEND|向量存储后端：milvus或sqlite；企业部署使用milvus。
MILVUS_URI|Milvus连接地址，通常http://127.0.0.1:19530。
MILVUS_TOKEN|Milvus鉴权凭证，通常为用户名:密码；保密。
MILVUS_COLLECTION|Milvus集合名称；不同环境是否共享需明确，勿随意更改。
MILVUS_ROOT_PASSWORD|初始化Milvus配置使用的管理员密码；修改此值不等于自动轮换现有服务密码。
OPERATIONS_TOKEN|运维接口访问密钥，用于受保护的运行配置查询；与普通用户凭证不同。
APP_WORKERS|Uvicorn进程数，代码允许1至4，默认1；增加前需评估模型并发容量。
EMBEDDING_TIMEOUT|单次Embedding调用超时，单位秒，默认30；在线检索同时受总预算限制。
RERANK_TIMEOUT|单次重排调用超时，单位秒，默认30；在线检索同时受总预算限制。
MODEL_MAX_TOKENS|聊天模型单次最大生成Token数，默认2048；不是中文字符数。
MODEL_DISABLE_THINKING|Qwen3关闭思考输出选项，默认true；需模型服务支持，不是关闭处理日志。
SESSION_RETENTION_DAYS|页面历史消息及会话保留天数，默认7，允许1至365；已清理数据不能恢复。
SESSION_CONTEXT_ROUNDS|模型最多参考的最近问答轮数，默认20，允许1至1000；不是页面历史条数上限。
SESSION_IDLE_SECONDS|会话空闲阈值，单位秒，默认1800；超时后不再携带此前上下文，历史仍按保留期可查。
SESSION_CLEANUP_INTERVAL_SECONDS|后台清理过期会话和检查点的检查间隔，单位秒，默认300。
TENANT_MESSAGES_PER_MINUTE|同企业所有账号共用的滚动60秒提问额度，默认20；匿名测试用户共用测试企业额度。
RETRIEVAL_TIMEOUT_SECONDS|整条在线检索总预算，包含Embedding、向量查询及重排，单位秒，默认15；不包含回答生成。
LOG_DIR|服务器日志根目录，默认项目var/logs；容器内路径应有持久化挂载。
LOG_TIMEZONE|日志日期和时间使用的时区，默认Asia/Shanghai。
LOG_RETENTION_DAYS|普通运行日志及不含正文的问答摘要保留天数，默认30，允许1至365。
LOG_DEBUG_CONTENT|是否记录完整问题、知识依据、模型输入输出等排障内容；true开启，生产按需启用。
LOG_DEBUG_RETENTION_DAYS|包含完整正文的排障记录保留天数，默认3，允许1至30；与普通日志保留期独立。
DEMO_AUTO_LOGIN|匿名测试页是否自动发放测试凭证；true免手填，正式平台账号接入后应关闭。
KNOWLEDGE_PATH|传统知识JSONL路径；语义检索部署主要从知识入库索引读取。
KNOWLEDGE_SOURCE_DIR|待入库知识文档目录，默认knowledge_sources；不要在里面同时放多个重复版本。
RAG_INDEX_PATH|本地知识索引路径，默认var/rag.sqlite3；实际元数据后端还取决于DATABASE_URL。
MEDIA_PATH|配图登记文件路径，默认data/media.json；知识配图须在此登记。
POSTGRES_USER|Compose新建PostgreSQL实例的初始化管理员账号；复用外部PG时以DATABASE_URL为准。
POSTGRES_DB|Compose新建PostgreSQL实例的初始化数据库名；不自动改名已有数据库。
POSTGRES_PASSWORD|Compose新建PostgreSQL实例的初始化管理员密码；更改环境变量不自动修改已有密码。
POSTGRES_PORT|Compose新建PostgreSQL实例映射到宿主机的端口；复用外部PG时以连接串为准。
APP_DB_USER|PostgreSQL初始化脚本创建的应用账号，通常不授予超级用户权限。
APP_DB_PASSWORD|应用数据库账号初始化密码；已有数据库密码需单独变更，不能只改此值。
MINIO_ROOT_USER|MinIO管理员用户名，需与Milvus访问配置匹配。
MINIO_ROOT_PASSWORD|MinIO管理员密码，需与Milvus访问配置匹配；保密。
ASSISTANT_UID|容器运行用户UID，部署脚本通常从当前宿主机用户自动取得。
ASSISTANT_GID|容器运行用户GID，部署脚本通常从当前宿主机用户自动取得。
COMPOSE_PROJECT_NAME|Docker Compose项目名，用于隔离容器、网络及数据卷命名；不要随意变更。
MODEL_NETWORK|复用模型容器的外部Docker网络名称。'''.splitlines())
PREFIX='# 参数说明 '
ASSIGN=re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=')

def annotate(raw):
    lines=raw.splitlines(keepends=True);result=[];unknown=set();count=0
    for line in lines:
        if line.startswith(PREFIX):continue
        match=ASSIGN.match(line)
        if match:
            key=match[1];value=line[match.end():].lstrip()
            # Do not insert comments inside multi-line dotenv string values.
            if value.startswith(('"',"'")) and not re.search(r'(?<!\\)'+re.escape(value[0]),value[1:]):
                raise ValueError('发现多行引号值，未修改文件；请先单独处理参数：'+key)
            description=DESCRIPTIONS.get(key)
            if description is None:
                unknown.add(key);description='项目自定义参数；保留原值，含义需结合使用它的配置或代码确认。'
            newline='\r\n' if line.endswith('\r\n') else '\n'
            result.append(PREFIX+key+'：'+description+newline);count+=1
        result.append(line)
    return ''.join(result),count,sorted(unknown)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--path',type=Path,default=ROOT/'.env');args=parser.parse_args();path=args.path.absolute()
    if path.is_symlink() or not path.is_file():raise SystemExit('未找到普通.env文件，或路径是符号链接；未修改。')
    raw=path.read_bytes();updated,count,unknown=annotate(raw.decode('utf-8'));encoded=updated.encode('utf-8')
    if encoded==raw:print('已有完整参数说明，无需修改。');return
    directory=path.parent/'backups'/('env-comments-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));directory.mkdir(parents=True,mode=0o700)
    backup=directory/'env.before';shutil.copyfile(path,backup);backup.chmod(0o600)
    fd,temp=tempfile.mkstemp(prefix='.env-comments-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as output:output.write(encoded)
        os.chmod(temp,0o600);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print('已为'+str(count)+'个参数添加中文说明；参数原始行未改变。')
    print('原配置备份：'+str(backup))
    if unknown:print('需补充说明的自定义参数名：'+', '.join(unknown))
    print('仅修改注释，不需要重启或重新入库。')
if __name__=='__main__':main()
