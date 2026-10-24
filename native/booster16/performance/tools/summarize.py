import pathlib,json,statistics,re
r=pathlib.Path('/workspace/shared/benchmark-build');out={'qualification':'NOT full-pipeline parity: official walking-only lacks camera/vision/brain/demo/SDK functional workload','cpu_budget':'same affinity CPUs0-8, Mesa LP_NUM_THREADS4, OMP/BLAS1; actual process thread counts differ and are recorded, not forced equal','baseline':{},'profiles':{},'limits':['profile timings are inclusive wall intervals across asynchronous threads and cannot be added as percentages','native profile RTF differs materially from pristine baseline, so use original3runs for throughput and profile only for attribution/count evidence','no per-frame file writes or third-person captures; original native camera/vision remains active','official baseline has no executed vision, not an optimization that disables an existing pipeline','process CPU includes reaped subprocesses; loop CPU field is parent only','OS thread sampling at100ms may miss short-lived peaks']}
for name in ['bhuman-normal','official-control']:
 ds=[json.loads(p.read_text()) for p in sorted((r/'runs').glob(name+'-*/result.json'))];out['baseline'][name]={'runs':ds,'median_rtf_loop':statistics.median(x['rtf_loop'] for x in ds),'median_rtf_startup_inclusive':statistics.median(x['rtf_including_startup_and_teardown'] for x in ds),'min_rtf_loop':min(x['rtf_loop'] for x in ds),'max_rtf_loop':max(x['rtf_loop'] for x in ds)}
for name in ['bhuman-profiled-1','official-profiled-1']:
 d=r/'runs'/name
 if not (d/'result.json').exists():continue
 log=(d/'run.log').read_text();stages=[]
 for n,c,ns in re.findall(r'PERF_STAGE name=(\S+) calls=(\d+) wall_ns=(\d+)',log):
  c=int(c);ns=int(ns);stages.append(dict(name=n,calls=c,wall_seconds=ns/1e9,mean_us=ns/c/1e3 if c else None))
 py=[json.loads(x) for x in re.findall(r'PERF_PYTHON (\{.*\})',log)]
 out['profiles'][name]={'run':json.loads((d/'result.json').read_text()),'stages':stages,'python_snapshots':py}
(r/'report/results.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:{'median_loop':v['median_rtf_loop'],'median_startup_inclusive':v['median_rtf_startup_inclusive']} for k,v in out['baseline'].items()},indent=2))
