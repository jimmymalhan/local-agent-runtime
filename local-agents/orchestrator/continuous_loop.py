#!/usr/bin/env python3
"""continuous_loop.py -- Never-stop task execution engine.

Runs forever processing the task queue. When empty, auto-generates new tasks.
Self-heals on failures. Scores every output.

Usage:
    python3 -m orchestrator.continuous_loop --forever
    python3 -m orchestrator.continuous_loop --project <id>
    python3 -m orchestrator.continuous_loop --all
"""
import os, sys, json, time, signal, argparse, logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional

BASE_DIR    = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
SKILLS_DIR  = os.path.join(BASE_DIR, "..", ".claude", "skills")
STOP_FILE   = os.path.join(BASE_DIR, ".stop")
PATTERNS_LOG = os.path.join(REPORTS_DIR, "learned_patterns.jsonl")

sys.path.insert(0, BASE_DIR)
Path(REPORTS_DIR).mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("continuous_loop")

try:
    from agents import run_task as _run_task, route as _route
except ImportError:
    def _run_task(t): return {"status":"ok","output":"","quality":0,"tokens_used":0,"elapsed_s":0.0,"agent_name":"stub"}
    def _route(t): return "executor"

try:
    from orchestrator.resource_guard import ResourceGuard
except ImportError:
    class ResourceGuard:
        def check(self):
            class S: ram_pct=0.0; action="normal"
            return S()

try:
    from dashboard.state_writer import update_agent, update_task_queue
    _DASH = True
except ImportError:
    _DASH = False
    def update_agent(*a, **k): pass
    def update_task_queue(*a, **k): pass

try:
    from tasks.task_suite import TASKS as _SUITE; _SUITE_OK=True
except ImportError:
    try: from tasks.task_suite_legacy import TASKS as _SUITE; _SUITE_OK=True
    except ImportError: _SUITE_OK=False; _SUITE=[]

_TPLS = [
    ("tdd",      "Add tests for {a}",        "Write unit tests for {a}: happy path, errors, edge cases."),
    ("doc",      "Document {a}",             "Write docstrings and comments for {a}. Include examples."),
    ("refactor", "Refactor {a} for clarity", "Refactor {a}: remove duplication, better naming, SOLID."),
    ("review",   "Code review {a}",          "Review {a} for bugs, security, and performance issues."),
    ("scaffold", "CI pipeline for {a}",      "Create GitHub Actions workflow for {a}: lint, test, build."),
]
_NID = 9000

def _now(): return datetime.now().isoformat()
def _day(): return date.today().strftime("%Y%m%d")
def _llog(): return os.path.join(REPORTS_DIR, f"loop_{_day()}.jsonl")
def _slog(): return os.path.join(REPORTS_DIR, f"session_{_day()}.json")
def _jl(p,r):
    try:
        with open(p,"a") as f: f.write(json.dumps(r)+"\n")
    except Exception: pass
def _ram():
    try: import psutil; return psutil.virtual_memory().percent
    except Exception: return 0.0


class ContinuousLoop:
    """Never-stop task execution engine.

    Processes the task queue forever. When empty, auto-generates new tasks.
    Self-heals on failures. Scores every output.
    """
    def __init__(self, project_id=None):
        self.project_id=project_id; self.guard=ResourceGuard()
        self._n=0; self._done=0; self._scores=[]; self._cf=0
        self._rescues=0; self._total=0; self._stopped=False
        self._cur=None; self._bk=0.0
        signal.signal(signal.SIGINT, self._sig)
        signal.signal(signal.SIGTERM, self._sig)
        log.info("ContinuousLoop init project=%s", project_id or "all")

    def run(self, project_id=None, max_iterations=None):
        """Main loop. Runs until stop_conditions() or max_iterations hit."""
        pid=project_id or self.project_id
        log.info("Loop start project=%s max=%s", pid, max_iterations)
        while not self._stopped:
            self._n += 1
            if max_iterations and self._n > max_iterations:
                log.info("max_iterations=%d -- stopping.", max_iterations); break
            s=self.guard.check(); ram=_ram()
            if s.action=="kill" or ram>90:
                log.warning("RAM %.1f%% -- 10s pause", ram)
                _jl(_llog(),{"ts":_now(),"event":"resource_pressure","ram_pct":ram})
                time.sleep(10); continue
            if self.stop_conditions(): log.info("Stop condition met."); break
            task=self.get_next_task(pid)
            if task is None:
                gen=self.auto_generate_tasks(pid)
                if not gen: log.info("Empty queue -- 30s wait."); time.sleep(30); continue
                task=self.get_next_task(pid)
                if task is None: time.sleep(5); continue
            self._cur=task; task["status"]="in_progress"; task.setdefault("attempts",0)
            self._dash_start(task)
            result=self._exec_retry(task)
            score=float(result.get("quality",0))
            self._scores.append(score); self._done+=1; self._total+=1
            if score>=60:
                self._cf=0; self._bk=0.0; self._complete(task,result)
                if score>=90: self.promote_pattern(task,result)
            else:
                self._cf+=1; self._bk=min(self._bk*2+5,60)
                self._fail(task,result)
                log.warning("FAIL %s score=%.0f bk=%.0fs", task.get("title"), score, self._bk)
            _jl(_llog(),{"ts":_now(),"event":"task_done","task_id":task.get("id"),
                         "title":task.get("title"),"score":score,"agent":result.get("agent_name"),
                         "elapsed_s":result.get("elapsed_s",0),"iter":self._n})
            self._dash_sum()
            if self._bk>0: time.sleep(self._bk)
        self._cur=None; self._write_session()
        log.info("Loop done n=%d tasks=%d avg=%.1f", self._n, self._done, self._avg())

    def get_next_task(self, pid=None):
        """Return next pending task from project queue, todo.md, or built-in suite."""
        t=self._from_pm(pid)
        if t: return t
        t=self._from_todo()
        if t: return t
        if _SUITE_OK:
            for t in _SUITE:
                if t.get("status") in (None,"pending","todo"): return dict(t)
        return None

    def _from_pm(self, pid):
        if not pid: return None
        f=os.path.join(BASE_DIR,"projects",pid,"tasks.json")
        if not os.path.exists(f): return None
        try:
            for t in json.load(open(f)):
                if t.get("status") in (None,"pending","todo"): return dict(t)
        except Exception as e: log.debug("PM err: %s", e)
        return None

    def _from_todo(self):
        p=os.path.join(BASE_DIR,"tasks","todo.md")
        if not os.path.exists(p): return None
        try:
            global _NID
            for line in open(p):
                line=line.strip()
                if line.startswith("- [ ]"):
                    t=line[5:].strip(); _NID+=1
                    return {"id":_NID,"title":t,"description":t,"category":"code_gen",
                            "status":"pending","source":"todo.md"}
        except Exception as e: log.debug("todo err: %s", e)
        return None

    def auto_generate_tasks(self, pid=None):
        """Generate 3-5 tasks when queue is empty.

        Reads completed task titles. Infers missing coverage (tests, docs, CI).
        Generates and persists new tasks. Logs generated count.
        """
        global _NID
        log.info("Auto-generating tasks project=%s", pid or "default")
        done=[]; area=pid or "local-agents"
        pd=os.path.join(BASE_DIR,"projects",pid) if pid else None
        if pd and os.path.exists(pd):
            tf=os.path.join(pd,"tasks.json")
            if os.path.exists(tf):
                try:
                    for t in json.load(open(tf)):
                        if t.get("status")=="done": done.append(t.get("title",""))
                except Exception: pass
        has_t=any("test"  in t.lower() for t in done)
        has_d=any("doc"   in t.lower() for t in done)
        has_c=any("ci"    in t.lower() or "pipeline" in t.lower() for t in done)
        has_r=any("review" in t.lower() for t in done)
        want=[]
        if not has_t: want.append("tdd")
        if not has_d: want.append("doc")
        if not has_c: want.append("scaffold")
        if not has_r: want.append("review")
        want.append("refactor")
        tasks=[]
        for cat,ttpl,dtpl in _TPLS:
            if cat not in want: continue
            _NID+=1
            tasks.append({"id":_NID,"title":ttpl.format(a=area),"description":dtpl.format(a=area),
                          "category":cat,"status":"pending","source":"auto_generated","generated_at":_now()})
            if len(tasks)>=5: break
        if tasks and pd:
            tf=os.path.join(pd,"tasks.json")
            try:
                ex=json.load(open(tf)) if os.path.exists(tf) else []
                ex.extend(tasks); json.dump(ex,open(tf,"w"),indent=2)
            except Exception as e: log.warning("persist err: %s",e)
        log.info("Auto-generated %d tasks for %s", len(tasks), area)
        _jl(_llog(),{"ts":_now(),"event":"auto_generated_tasks","project":area,
                     "count":len(tasks),"titles":[t["title"] for t in tasks]})
        return tasks

    def _exec_retry(self, task):
        """3-attempt execution: original -> decompose -> context enrichment."""
        r=self._exec(task)
        if r.get("quality",0)>=60: return r
        log.info("Attempt 1 score=%.0f -- decomposing", r.get("quality",0))
        task["_p1"]=r
        r2=self.retry_with_different_approach(task,r)
        if r2.get("quality",0)>=60: return r2
        log.info("Attempt 2 score=%.0f -- context", r2.get("quality",0))
        task["_p2"]=r2
        r3=self.retry_with_different_approach(task,r2)
        return max([r,r2,r3],key=lambda x:x.get("quality",0))

    def _exec(self, task):
        task["attempts"]=task.get("attempts",0)+1; t0=time.time()
        try: return _run_task(task)
        except Exception as e:
            return {"status":"error","output":str(e),"quality":0,"tokens_used":0,
                    "elapsed_s":time.time()-t0,"agent_name":_route(task),"error":str(e)}

    def retry_with_different_approach(self, task, prev):
        """attempt 1 -> subtask decomposition; attempt 2+ -> context enrichment."""
        if task.get("attempts",1)==1: return self._decomp(task,prev)
        return self._enrich(task,prev)

    def _decomp(self, task, prev):
        """Break into 2 subtasks; run each; return averaged result."""
        log.info("Strategy: decompose '%s'", task.get("title"))
        rs=[self._exec(dict(task,title=task.get("title")+s,
                            category=task.get("category","code_gen"),attempts=0))
            for s in [" -- Part 1: structure"," -- Part 2: logic"]]
        best=max(rs,key=lambda r:r.get("quality",0))
        return dict(best,output="\n\n---\n\n".join(r.get("output","") for r in rs),
                    quality=round(sum(r.get("quality",0) for r in rs)/len(rs),1))

    def _enrich(self, task, prev):
        """Enrich with previous attempt context; retry."""
        log.info("Strategy: context enrichment '%s'", task.get("title"))
        e=dict(task,
               description=(f"{task.get('description','')}\n\n"
                             f"[Prev score {prev.get('quality',0):.0f}/100]\n"
                             f"{str(prev.get('output',''))[:500]}\n\nImprove: correctness+completeness."),
               codebase_path=BASE_DIR, attempts=0)
        r=self._exec(e); r["retry_strategy"]="codebase_context"; return r

    def promote_pattern(self, task, result):
        """When score>=90, append approach to .claude/skills/<cat>.md and JSONL."""
        pat={"ts":_now(),"task_title":task.get("title"),"task_category":task.get("category"),
             "score":result.get("quality"),"agent":result.get("agent_name"),
             "retry_strategy":result.get("retry_strategy","first_attempt"),
             "approach_notes":(f"cat={task.get('category')} agent={result.get('agent_name')} "
                               f"score={result.get('quality')}/100 attempt={task.get('attempts',1)}"),
             "output_snippet":str(result.get("output",""))[:300]}
        _jl(PATTERNS_LOG,pat)
        sd=Path(SKILLS_DIR)
        if sd.exists():
            sf=sd/f"{task.get('category','general')}.md"
            try:
                with open(sf,"a") as f:
                    f.write(f"\n\n## Pattern That Works (auto-learned {_now()[:10]})\n"
                            f"**Task:** {task.get('title')}\n**Score:** {result.get('quality')}/100\n"
                            f"**Agent:** {result.get('agent_name')}\n**Strategy:** {pat['retry_strategy']}\n"
                            f"**Notes:** {pat['approach_notes']}\n")
                log.info("Promoted pattern -> %s", sf)
            except Exception as e: log.debug("Skill write err: %s", e)

    def stop_conditions(self):
        """Return True to stop: .stop file, 5 failures, RAM>90%, rescue>10%."""
        if os.path.exists(STOP_FILE): log.info("Stop file -- halting."); return True
        if self._cf>=5: log.error("5 consecutive failures -- stopping."); return True
        if _ram()>90: log.warning("RAM>90%% -- health stop."); return True
        if self._total>0 and (self._rescues/self._total*100)>10:
            log.warning("Rescue>10%% -- local-first."); return True
        return False

    def _complete(self, task, result):
        task.update({"status":"done","completed_at":_now(),"final_score":result.get("quality",0)})
        self._persist(task)
        update_agent(task.get("_agent",result.get("agent_name","executor")),status="idle",task="")
        update_task_queue(completed_delta=1,in_progress_delta=-1)
        log.info("DONE '%s' score=%.0f", task.get("title"), result.get("quality",0))

    def _fail(self, task, result):
        task.update({"status":"failed","failed_at":_now(),"final_score":result.get("quality",0)})
        self._persist(task)
        update_agent(task.get("_agent",result.get("agent_name","executor")),status="idle",task="")
        update_task_queue(failed_delta=1,in_progress_delta=-1)

    def _persist(self, task):
        pid=task.get("project_id") or self.project_id
        if not pid: return
        tf=os.path.join(BASE_DIR,"projects",pid,"tasks.json")
        if not os.path.exists(tf): return
        try:
            ts=json.load(open(tf))
            for t in ts:
                if t.get("id")==task.get("id"): t.update(task); break
            json.dump(ts,open(tf,"w"),indent=2)
        except Exception as e: log.debug("Persist err: %s",e)

    def _dash_start(self, task):
        an=_route(task); task["_agent"]=an
        update_agent(an,status="running",task=task.get("title",""),task_id=task.get("id"))
        update_task_queue(in_progress_delta=1,pending_delta=-1)

    def _dash_sum(self):
        """Update state.json continuous_loop section after every task."""
        if not _DASH: return
        try:
            from dashboard.state_writer import _read, _write
            s=_read()
            s["continuous_loop"]={"current_task":self._cur.get("title") if self._cur else None,
                                  "tasks_completed_today":self._done,"quality_avg":round(self._avg(),1),
                                  "consecutive_failures":self._cf,"iterations":self._n,"last_activity":_now()}
            _write(s)
        except Exception as e: log.debug("Dash err: %s",e)

    def _write_session(self):
        try:
            json.dump({"ts":_now(),"project_id":self.project_id,"iterations":self._n,
                       "tasks_completed":self._done,"quality_avg":round(self._avg(),1),
                       "consec_fail_end":self._cf,"rescue_calls":self._rescues,"total":self._total},
                      open(_slog(),"w"),indent=2)
            log.info("Session -> %s", _slog())
        except Exception as e: log.debug("Session err: %s",e)

    def _sig(self,signum,frame):
        log.info("%s -- finishing task then stopping.","SIGINT" if signum==2 else "SIGTERM")
        self._stopped=True

    def _avg(self):
        return sum(self._scores)/len(self._scores) if self._scores else 0.0


def main():
    p=argparse.ArgumentParser(description="continuous_loop -- never-stop task execution engine")
    p.add_argument("--project"); p.add_argument("--all",action="store_true")
    p.add_argument("--forever",action="store_true"); p.add_argument("--max-iterations",type=int,default=None)
    a=p.parse_args()
    loop=ContinuousLoop(project_id=a.project)
    mi=None if a.forever else a.max_iterations
    if a.all:
        pd=os.path.join(BASE_DIR,"projects")
        pids=[d for d in os.listdir(pd) if os.path.isdir(os.path.join(pd,d))] if os.path.exists(pd) else []
        if not pids: loop.run(max_iterations=mi)
        else:
            for pid in pids:
                if loop._stopped: break
                ContinuousLoop(project_id=pid).run(project_id=pid,max_iterations=mi)
    else:
        loop.run(project_id=a.project,max_iterations=mi)

if __name__=="__main__": main()
