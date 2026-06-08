#!/usr/bin/env python3
"""
IntelliOps 诊断脚本模板。

使用方式：
1. 复制此模板
2. 修改 TARGET_SERVICE 和 DIAGNOSIS_TYPE
3. 实现 check() 函数
4. 运行: python script.py

注意：此脚本是只读诊断脚本，不应有任何写操作。
"""

import subprocess
import json
import sys
from datetime import datetime

# ===== 配置区域 =====
TARGET_SERVICE = "{{SERVICE_NAME}}"       # 替换为目标服务名
DIAGNOSIS_TYPE = "{{DIAGNOSIS_TYPE}}"     # 替换为诊断类型：metrics/logs/health/config
TIMEOUT_SEC = 30
# ===================

def now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def check_health() -> dict:
    """健康检查"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             f"http://{TARGET_SERVICE}:8080/health"],
            capture_output=True, text=True, timeout=TIMEOUT_SEC
        )
        return {"status": "ok" if result.stdout.strip() == "200" else "unhealthy", "http_code": result.stdout.strip()}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def check_metrics() -> dict:
    """采集指标"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"http://{TARGET_SERVICE}:8080/actuator/metrics"],
            capture_output=True, text=True, timeout=TIMEOUT_SEC
        )
        return {"status": "ok", "metrics_available": len(result.stdout) > 0}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def check_logs() -> dict:
    """采集最近日志"""
    try:
        result = subprocess.run(
            ["journalctl", "-u", TARGET_SERVICE, "--since", "30 minutes ago",
             "-p", "err", "--no-pager"],
            capture_output=True, text=True, timeout=TIMEOUT_SEC
        )
        error_count = len([l for l in result.stdout.split("\n") if l.strip()])
        return {"status": "ok", "error_lines_last_30min": error_count}
    except Exception as e:
        return {"status": "error", "error": str(e)}

CHECKS = {
    "health": check_health,
    "metrics": check_metrics,
    "logs": check_logs,
}

if __name__ == "__main__":
    check_fn = CHECKS.get(DIAGNOSIS_TYPE, check_health)
    result = {
        "timestamp": now(),
        "target": TARGET_SERVICE,
        "type": DIAGNOSIS_TYPE,
        "result": check_fn(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
