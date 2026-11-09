"""Host-only read-only Docker and NVIDIA sampling. Never mount Docker into chatbot."""
import csv
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import quote

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=4)
        self.path = path
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)

class Probe:
    def __init__(self, containers, socket_path='/var/run/docker.sock'):
        self.containers = containers
        self.socket_path = socket_path
        self.errors = {}
        self.metadata = {}; self.cgroups = {}; self.pids = {}; self.gpu_cache=([],[],None); self.gpu_at=0
    def get(self, path):
        client = UnixHTTP(self.socket_path)
        try:
            client.request('GET', path)
            response = client.getresponse()
            if response.status != 200:
                raise RuntimeError('docker_http_'+str(response.status))
            return json.loads(response.read(4_000_000))
        finally:
            client.close()
    def describe(self):
        for stage, name in self.containers.items():
            data = self.get('/containers/'+quote(name, safe='')+'/json')
            host = data.get('HostConfig', {})
            try:
                pid=data['State']['Pid']
                relative=next(line.split(':',2)[2] for line in Path('/proc/'+str(pid)+'/cgroup').read_text().splitlines() if line.startswith('0::'))
                cgroup=Path('/sys/fs/cgroup')/relative.lstrip('/')
                if (cgroup/'cpu.stat').is_file():self.cgroups[stage]=cgroup
                top=self.get('/containers/'+quote(name,safe='')+'/top?ps_args=-eo%20pid')
                self.pids[stage]={int(r[0]) for r in top.get('Processes',[]) if r and str(r[0]).isdigit()}
            except (OSError,KeyError,StopIteration):pass
            self.metadata[stage] = {'container_name': name, 'container_id': data['Id'],
                'image': data.get('Config', {}).get('Image'), 'image_id': data.get('Image'),
                'cpu_quota': host.get('CpuQuota'), 'cpu_period': host.get('CpuPeriod'),
                'nano_cpus': host.get('NanoCpus'), 'cpuset_cpus': host.get('CpusetCpus'),
                'memory_limit_bytes': host.get('Memory'), 'device_requests': host.get('DeviceRequests'),
                'deployment_directory': (data.get('Config', {}).get('Labels') or {}).get('com.docker.compose.project.working_dir')}
        return self.metadata
    def sample(self):
        if time.monotonic()-self.gpu_at>=1:
            self.gpu_cache=nvidia();self.gpu_at=time.monotonic()
            # Ollama can spawn a model runner only after the first query.
            for stage,name in self.containers.items():
                try:
                    top=self.get('/containers/'+quote(name,safe='')+'/top?ps_args=-eo%20pid')
                    self.pids[stage]={int(r[0]) for r in top.get('Processes',[]) if r and str(r[0]).isdigit()}
                except Exception:pass
        gpu, processes, gpu_error = self.gpu_cache
        result = {}
        for stage, name in self.containers.items():
            try:
                if stage in self.cgroups:
                    group=self.cgroups[stage]
                    stat=dict(line.split() for line in (group/'cpu.stat').read_text().splitlines())
                    data={'id':self.metadata[stage]['container_id'],
                          'cpu_stats':{'cpu_usage':{'total_usage':int(stat['usage_usec'])*1000,
                                       'usage_in_kernelmode':int(stat.get('system_usec','0'))*1000,
                                       'usage_in_usermode':int(stat.get('user_usec','0'))*1000}},
                          'memory_stats':{'usage':int((group/'memory.current').read_text())}}
                    pids=self.pids.get(stage,set())
                else:
                    data = self.get('/containers/'+quote(name, safe='')+'/stats?stream=false&one-shot=true')
                    top = self.get('/containers/'+quote(name, safe='')+'/top?ps_args=-eo%20pid')
                    pids = {int(r[0]) for r in top.get('Processes', []) if r and str(r[0]).isdigit()}
                own = [p for p in processes if p['pid'] in pids]
                ids = {p['gpu_uuid'] for p in own}
                memory = data.get('memory_stats', {}); cpu = data['cpu_stats']['cpu_usage']
                cache = memory.get('stats', {}).get('inactive_file', memory.get('stats', {}).get('total_inactive_file', 0))
                result[stage] = {'timestamp': time.time(), 'container_id': data['id'],
                    'cpu_total_ns': cpu['total_usage'], 'kernel_cpu_ns': cpu.get('usage_in_kernelmode'),
                    'user_cpu_ns': cpu.get('usage_in_usermode'), 'online_cpus': data.get('cpu_stats', {}).get('online_cpus'),
                    'memory_bytes': memory.get('usage', 0),
                    'memory_working_set_bytes': max(0, memory.get('usage', 0)-cache),
                    'gpu_process_memory_mib': sum(p['memory_mib'] for p in own) if own else None,
                    'gpu_processes': own, 'gpus': [g for g in gpu if g['uuid'] in ids],
                    'gpu_status': gpu_error or ('process_mapped' if own else 'no_mapped_gpu_process')}
            except Exception as error:
                self.errors[stage] = type(error).__name__
        return result

def number(value):
    try:
        return float(value.strip())
    except ValueError:
        return None

def nvidia():
    try:
        command = ['nvidia-smi', '--query-gpu=uuid,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu', '--format=csv,noheader,nounits']
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=True)
        cards = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) != 7:
                continue
            cards.append(dict(zip(('uuid','utilization_percent','memory_utilization_percent','memory_used_mib','memory_total_mib','power_w','temperature_c'), [row[0].strip()]+[number(x) for x in row[1:]])))
        result = subprocess.run(['nvidia-smi','--query-compute-apps=pid,gpu_uuid,used_gpu_memory','--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
        processes = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) == 3 and row[0].strip().isdigit() and number(row[2]) is not None:
                processes.append({'pid': int(row[0]), 'gpu_uuid': row[1].strip(), 'memory_mib': number(row[2])})
        return cards, processes, None
    except Exception as error:
        return [], [], 'unavailable_'+type(error).__name__

def publish(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name+'.tmp-'+str(os.getpid()))
    fd = os.open(temporary, os.O_CREAT|os.O_TRUNC|os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(temporary, path)
