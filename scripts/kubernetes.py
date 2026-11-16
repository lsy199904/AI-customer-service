"""Small kubectl orchestrator. Uses stdlib only; never prints Secret payloads."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from configure_external import ROOT, initialize, read_env, validate_local

DEPLOY_KEYS = {'ASSISTANT_IMAGE', 'COMPOSE_PROJECT_NAME', 'APP_HOST', 'APP_PORT'}
SECRET_KEYS = {'DATABASE_URL', 'AUTH_SECRET', 'OPERATIONS_TOKEN', 'MILVUS_TOKEN',
               'MODEL_API_KEY', 'EMBEDDING_API_KEY', 'RERANK_API_KEY'}
PATHS = {'HOST': '0.0.0.0', 'LOG_DIR': '/srv/assistant/var/logs',
         'KNOWLEDGE_SOURCE_DIR': '/srv/assistant/knowledge_sources',
         'MEDIA_PATH': '/srv/assistant/data/media.json', 'PDF_MEDIA_DIR': '/srv/assistant/var/pdf_media',
         'DATABASE_PATH': '/srv/assistant/var/assistant.db', 'RAG_INDEX_PATH': '/srv/assistant/var/rag.sqlite3'}


def validate_image(image):
    registry = image.split('/', 1)[0]
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]*', image)
            or '/' not in image or not ('.' in registry or ':' in registry or registry == 'localhost')
            or image.endswith(':latest') or not (':' in image.rsplit('/', 1)[-1] or '@sha256:' in image)):
        raise ValueError('生产ASSISTANT_IMAGE请填写公司仓库完整地址和唯一版本标签或digest，不能为latest')


def settings(validate=True):
    v = validate_local() if validate else read_env(ROOT / '.env')
    for key in ('K8S_CONTEXT', 'K8S_NAMESPACE', 'K8S_APP_NAME', 'K8S_PVC_NAME'):
        if not v.get(key):
            raise ValueError('请填写' + key)
    for key in ('K8S_NAMESPACE', 'K8S_APP_NAME', 'K8S_PVC_NAME'):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', v[key]):
            raise ValueError(key + '需为小写字母、数字、短横线，最长40字符')
    if validate:validate_image(v.get('ASSISTANT_IMAGE', ''))
    timeout = int(v.get('K8S_JOB_TIMEOUT', '1800'))
    if not 60 <= timeout <= 86400:
        raise ValueError('K8S_JOB_TIMEOUT需为60至86400秒')
    return v


def labels(v):
    return {'app.kubernetes.io/name': v['K8S_APP_NAME'],
            'smarttitu-deployment': hashlib.sha256(v['DEPLOYMENT_ID'].encode()).hexdigest()[:32]}


def meta(v, name):
    return {'name': name, 'namespace': v['K8S_NAMESPACE'], 'labels': labels(v)}


def resources(v):
    return {'requests': {'cpu': v.get('K8S_CPU_REQUEST', '500m'), 'memory': v.get('K8S_MEMORY_REQUEST', '1Gi')},
            'limits': {'cpu': v.get('K8S_CPU_LIMIT', '2'), 'memory': v.get('K8S_MEMORY_LIMIT', '4Gi')}}


def configuration(v):
    app = {k: value for k, value in v.items() if not k.startswith('K8S_') and k not in DEPLOY_KEYS and not k.startswith(('PG_ADMIN_', 'MILVUS_ADMIN_', 'CLOUD_PREPARE_'))}
    app.update(PATHS, PORT=v.get('APP_PORT', '8201'))
    secret = {k: app.pop(k) for k in list(app) if k in SECRET_KEYS or any(s in k for s in ('SECRET', 'PASSWORD', 'API_KEY', 'TOKEN'))}
    name = v['K8S_APP_NAME']
    return [dict(apiVersion='v1', kind='ConfigMap', metadata=meta(v, name+'-config'), data=app),
            dict(apiVersion='v1', kind='Secret', metadata=meta(v, name+'-secret'), type='Opaque', stringData=secret)]


def pod(v):
    name = v['K8S_APP_NAME']
    container = {'name': 'assistant', 'image': v['ASSISTANT_IMAGE'], 'imagePullPolicy': 'IfNotPresent',
                 'envFrom': [{'configMapRef': {'name': name+'-config'}}, {'secretRef': {'name': name+'-secret'}}],
                 'resources': resources(v), 'volumeMounts': [{'name': 'var', 'mountPath': '/srv/assistant/var'}],
                 'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}}}
    spec = {'containers': [container], 'restartPolicy': 'Always',
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001, 'fsGroup': 10001},
            'terminationGracePeriodSeconds': 190, 'automountServiceAccountToken': False,
            'volumes': [{'name': 'var', 'persistentVolumeClaim': {'claimName': v['K8S_PVC_NAME']}}]}
    if v.get('K8S_IMAGE_PULL_SECRET'):
        spec['imagePullSecrets'] = [{'name': v['K8S_IMAGE_PULL_SECRET']}]
    return {'metadata': {'labels': labels(v)}, 'spec': spec}


def manifest(v):
    name = v['K8S_APP_NAME']; port = int(v.get('APP_PORT', '8201'))
    if not 1 <= port <= 65535:
        raise ValueError('APP_PORT无效')
    template = pod(v); template['metadata']['labels']['smarttitu-role'] = 'app'
    selector = {**labels(v), 'smarttitu-role': 'app'}
    container = template['spec']['containers'][0]
    container['ports'] = [{'name': 'http', 'containerPort': port}]
    probe = lambda path: {'httpGet': {'path': '/smart-bot/'+path, 'port': 'http'}, 'timeoutSeconds': 10, 'periodSeconds': 15}
    container['startupProbe'] = {**probe('ready'), 'failureThreshold': 40}
    container['readinessProbe'] = {**probe('ready'), 'failureThreshold': 3}
    container['livenessProbe'] = {**probe('health'), 'failureThreshold': 6}
    deploy = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta(v, name),
              'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': selector}, 'template': template}}
    service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': meta(v, name),
               'spec': {'type': 'ClusterIP', 'selector': selector, 'ports': [{'port': 80, 'targetPort': 'http', 'name': 'http'}]}}
    pvc = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': meta(v, v['K8S_PVC_NAME']),
           'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': v.get('K8S_STORAGE_SIZE', '20Gi')}}}}
    if v.get('K8S_STORAGE_CLASS'):
        pvc['spec']['storageClassName'] = v['K8S_STORAGE_CLASS']
    return deploy, service, pvc


class Kubernetes:
    def __init__(self, v):
        self.v = v
        self.base = ['kubectl', '--context', v['K8S_CONTEXT'], '--namespace', v['K8S_NAMESPACE']]

    def run(self, *args, payload=None, capture=False):
        result = subprocess.run(self.base+list(args), input=json.dumps(payload) if payload is not None else None,
                                text=True, capture_output=True)
        if result.returncode:
            # kubectl apply errors can contain the entire Secret, including last-applied data.
            raise RuntimeError('kubectl操作失败：'+args[0]+'；请核对上下文、命名空间、权限和资源事件（未输出潜在凭证）')
        if not capture and result.stdout:
            print(result.stdout.strip(), flush=True)
        return result.stdout

    def get(self, kind, name):
        value = self.run('get', kind, name, '--ignore-not-found', '-o', 'json', capture=True)
        return json.loads(value) if value.strip() else None

    def apply(self, value):
        self.run('apply', '-f', '-', payload=value)

    def ownership(self, kind, name, allow_unmarked=False):
        existing = self.get(kind, name)
        if existing and existing.get('metadata', {}).get('labels', {}).get('smarttitu-deployment') != labels(self.v)['smarttitu-deployment']:
            if not allow_unmarked:
                raise ValueError('同名'+kind+'不属于本部署，拒绝覆盖：'+name)
        return existing

    def ensure_namespace(self):
        if not self.get('namespace', self.v['K8S_NAMESPACE']):
            self.apply({'apiVersion':'v1','kind':'Namespace','metadata':{'name':self.v['K8S_NAMESPACE']}})

    def pause(self):
        name = self.v['K8S_APP_NAME']
        existing = self.ownership('deployment', name)
        if existing:
            self.run('scale', 'deployment/'+name, '--replicas=0')
            # Wait for old Pod termination before another node mounts an RWO volume.
            self.run('wait', '--for=delete', 'pod', '-l', 'smarttitu-deployment='+labels(self.v)['smarttitu-deployment']+',smarttitu-role=app', '--timeout=240s')

    def job(self, command, cloud_values=None):
        v = self.v; name = v['K8S_APP_NAME']+'-'+('cloud' if cloud_values is not None else 'init')+'-'+str(time.time_ns())[-12:]
        template = pod(v); template['metadata']['labels']['smarttitu-role'] = 'maintenance'
        spec = template['spec']; container = spec['containers'][0]
        spec['restartPolicy'] = 'Never'
        container['command'] = command
        if cloud_values is not None:
            secret_name = name
            self.apply({'apiVersion':'v1','kind':'Secret','metadata':meta(v,secret_name), 'type':'Opaque','stringData':cloud_values})
            container['envFrom'] = [{'secretRef':{'name':secret_name}}]
            container.pop('volumeMounts'); spec.pop('volumes')
        job = {'apiVersion':'batch/v1','kind':'Job','metadata':meta(v,name),
               'spec':{'backoffLimit':0,'activeDeadlineSeconds':int(v.get('K8S_JOB_TIMEOUT','1800')),
                       'ttlSecondsAfterFinished':86400,'template':template}}
        try:
            self.apply(job)
            deadline = time.monotonic()+int(v.get('K8S_JOB_TIMEOUT','1800'))+30
            while time.monotonic() < deadline:
                state = self.get('job', name) or {}
                status = state.get('status', {})
                if status.get('succeeded'):
                    self.run('logs', 'job/'+name)
                    return
                if status.get('failed'):
                    self.run('logs', 'job/'+name)
                    raise RuntimeError('初始化Job失败；应用保持停止，修正配置后重新执行同一命令。Job：'+name)
                time.sleep(3)
            raise RuntimeError('等待Job超时，请查看Pod调度、镜像拉取和PVC事件。Job：'+name)
        finally:
            if cloud_values is not None:
                # Remove admin-bearing Pod as well as Secret; neither is used by app.
                self.run('delete','job',name,'--ignore-not-found','--wait=true')
                self.run('delete','secret',secret_name,'--ignore-not-found')


def cloud_init():
    path = ROOT / '.env.cloud'
    if path.exists():
        print('.env.cloud已存在，不覆盖管理员配置。'); return
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('# 私有管理员配置，禁止提交Git；业务账号/库名/密码从.env的DATABASE_URL读取。\n'
                '# 实例、VPC、白名单由云平台先开通。已有业务库可设false，仅检查连接。\n'
                'CLOUD_PREPARE_PG=true\nPG_ADMIN_URL=\n'
                '# Serverless通常由平台分配数据库，保持false；支持建库且需自动创建时设true。\n'
                'CLOUD_PREPARE_MILVUS=false\nMILVUS_ADMIN_TOKEN=\n')
    print('已生成私有.env.cloud，填写后执行cloud.sh prepare。')


def cloud_values(v):
    admin = read_env(ROOT / '.env.cloud')
    allowed = {'CLOUD_PREPARE_PG','PG_ADMIN_URL','CLOUD_PREPARE_MILVUS','MILVUS_ADMIN_TOKEN'}
    if set(admin)-allowed:
        raise ValueError('.env.cloud含未知参数')
    for key in ('CLOUD_PREPARE_PG','CLOUD_PREPARE_MILVUS'):
        if admin.get(key) not in ('true','false'):
            raise ValueError(key+'需为true或false')
    return {**{k:v[k] for k in ('DATABASE_URL','MILVUS_URI','MILVUS_TOKEN','MILVUS_DATABASE')}, **admin}


@contextmanager
def operation_lock():
    directory = ROOT/'deploy/generated'; directory.mkdir(parents=True,exist_ok=True)
    with open(directory/'operation.lock', 'a') as handle:
        try:fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('本目录已有部署操作进行中，请勿并发执行') from None
        try:yield
        finally:fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description='Kubernetes应用部署；数据库及模型均使用外部服务')
    parser.add_argument('action', choices=['init','build','render','deploy','update-knowledge','update-config','update-app','status','logs','stop','cloud'])
    parser.add_argument('subaction', nargs='?', choices=['init','prepare'])
    parser.add_argument('--rebuild', action='store_true', help='仅update-knowledge使用；Embedding/切片变化时全量重建向量')
    parser.add_argument('--docker', action='store_true', help='云端准备在研发Docker运行，不连接Kubernetes')
    args = parser.parse_args()
    if args.rebuild and args.action != 'update-knowledge':raise ValueError('--rebuild只用于update-knowledge')
    if args.action == 'init':initialize(); return
    if args.action == 'cloud' and args.subaction == 'init':cloud_init(); return
    if args.action == 'build':
        v = read_env(ROOT/'.env'); image=v.get('ASSISTANT_IMAGE','')
        validate_image(image)
        if '@sha256:' in image:raise ValueError('build需要可写的唯一版本标签，不能使用digest')
        subprocess.run(['docker','build','-t',image,'.'],cwd=ROOT,check=True)
        subprocess.run(['docker','push',image],check=True); return
    if args.action == 'cloud' and args.docker:
        v = read_env(ROOT/'.env'); values=cloud_values(v)
        subprocess.run(['docker','run','--rm','--network','host',
                        *[arg for key in values for arg in ('--env',key)],v['ASSISTANT_IMAGE'],'python','-m','app.cloud'],
                       env={**os.environ,**values},check=True); return
    v = settings(validate=args.action not in ('status','logs','stop','cloud'))
    kube = Kubernetes(v); name=v['K8S_APP_NAME']
    if args.action == 'render':
        directory = ROOT/'deploy/generated'; directory.mkdir(parents=True,exist_ok=True)
        # Review manifest intentionally omits Secret and config values.
        fd=os.open(directory/'kubernetes.json',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'apiVersion':'v1','kind':'List','items':list(manifest(v))},f,indent=2)
        print('已生成deploy/generated/kubernetes.json（不含密钥），此文件仅供审阅；部署用production.sh deploy。'); return
    if args.action == 'status':
        for kind in ('deployment','service','pvc','job','pod'):kube.run('get',kind,'-l','app.kubernetes.io/name='+name)
        return
    if args.action == 'logs':kube.run('logs','deployment/'+name,'--tail=100'); return
    if args.action == 'stop':kube.pause(); return
    if args.action == 'cloud':
        if args.subaction != 'prepare':raise ValueError('使用cloud.sh init或cloud.sh prepare')
        kube.ensure_namespace(); kube.job(['python','-m','app.cloud'],cloud_values(v)); return
    with operation_lock():
        kube.ensure_namespace()
        for kind,suffix in [('deployment',''),('service',''),('configmap','-config'),('secret','-secret')]:kube.ownership(kind,name+suffix)
        deploy, service, pvc = manifest(v)
        if v.get('K8S_CREATE_PVC','true') == 'true':
            existing=kube.ownership('pvc',v['K8S_PVC_NAME'])
            if not existing:kube.apply(pvc)
        elif not kube.get('pvc',v['K8S_PVC_NAME']):raise ValueError('配置的已有PVC不存在')
        # Avoid changing schema/knowledge while the previous application is serving.
        kube.pause()
        for resource in configuration(v):kube.apply(resource)
        if args.action in ('deploy','update-knowledge','update-app'):
            command=['sh','-ec','python -m app.deployment initialize && python manage.py ingest'+(' --rebuild' if args.rebuild else '')+' && python manage.py doctor --models']
        else:
            # New embedding settings cannot restart against an absent/incompatible collection.
            command=['sh','-ec','python -m app.deployment check && python manage.py doctor --models']
        kube.job(command)
        kube.apply(service); kube.apply(deploy)
        kube.run('rollout','status','deployment/'+name,'--timeout=600s')
        print('部署完成。请由平台Ingress将HTTPS /smart-bot原样转发至本Service:80，关闭SSE缓冲。')


if __name__ == '__main__':
    try:main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error,(ValueError,RuntimeError)) else '执行失败，请检查工具、文件权限或上一阶段结果',file=sys.stderr)
        raise SystemExit(1)
