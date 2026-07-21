#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
MANIFEST_PATH = DATA_DIR / "manifest.json"
MASTER_PATH = DATA_DIR / "security_master.csv"
COLUMNS = ["code","name","exchange","open","close","high","low","pre_close","change","pct","volume","amount","source"]


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def ymd(s: str) -> str:
    s = s.replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"日期格式应为YYYY-MM-DD或YYYYMMDD：{s}")
    return s


def iso(s: str) -> str:
    s = ymd(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"schema_version":1,"available_dates":[],"latest":None,"updated_at":None,"days":{}}


def save_manifest(manifest: dict) -> None:
    dates = sorted(set(manifest.get("available_dates", [])))
    manifest["available_dates"] = dates
    manifest["latest"] = dates[-1] if dates else None
    manifest["updated_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_exchange(code: str, exchange: str = "") -> str:
    exchange = str(exchange or "").upper()
    if exchange in {"SSE","SH"}: return "SSE"
    if exchange in {"SZSE","SZ"}: return "SZSE"
    if exchange in {"BSE","BJ"}: return "BSE"
    if code.startswith(("4","8")): return "BSE"
    if code.startswith(("5","6","9")): return "SSE"
    return "SZSE"


def validate(df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise RuntimeError(f"缺少字段：{sorted(missing)}")
    out = df[COLUMNS].copy()
    out["code"] = out["code"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6)
    for c in ["open","close","high","low","pre_close","change","pct","volume","amount"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out[out["code"].str.fullmatch(r"\d{6}") & out["close"].gt(0)].drop_duplicates("code", keep="last")
    out["name"] = out["name"].fillna("").astype(str)
    out["exchange"] = [normalize_exchange(c,e) for c,e in zip(out["code"],out["exchange"])]
    if len(out) < 1000:
        raise RuntimeError(f"{trade_date}仅得到{len(out)}条有效行情，低于安全阈值1000，拒绝写入")
    return out.sort_values("code").reset_index(drop=True)


def tushare_master(pro) -> pd.DataFrame:
    if MASTER_PATH.exists():
        try:
            m = pd.read_csv(MASTER_PATH, dtype={"code":str})
            if len(m) > 1000:
                return m
        except Exception:
            pass
    frames=[]
    for status in ["L","D","P"]:
        d=pro.stock_basic(exchange="",list_status=status,fields="ts_code,symbol,name,exchange,market,list_date,delist_date")
        if d is not None and not d.empty: frames.append(d)
    if not frames: raise RuntimeError("TuShare stock_basic为空")
    m=pd.concat(frames,ignore_index=True).drop_duplicates("ts_code",keep="last")
    m=m.rename(columns={"symbol":"code"})
    m[["code","name","exchange","market","list_date","delist_date"]].to_csv(MASTER_PATH,index=False,encoding="utf-8-sig")
    return m


def fetch_tushare(trade_date: str, token: str) -> pd.DataFrame:
    import tushare as ts
    if not token: raise RuntimeError("未配置TUSHARE_TOKEN")
    pro=ts.pro_api(token)
    d8=ymd(trade_date)
    df=pro.daily(trade_date=d8,fields="ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount")
    if df is None or df.empty: raise RuntimeError("TuShare当日日线为空")
    master=tushare_master(pro)[["code","name","exchange"]]
    df["code"]=df["ts_code"].str[:6]
    df=df.merge(master,on="code",how="left")
    df=df.rename(columns={"pct_chg":"pct","vol":"volume"})
    # TuShare成交量单位为手，成交额单位为千元；统一转换为股和元。
    df["volume"]=pd.to_numeric(df["volume"],errors="coerce")*100
    df["amount"]=pd.to_numeric(df["amount"],errors="coerce")*1000
    df["source"]="tushare"
    return validate(df,iso(trade_date))


def fetch_akshare_latest(trade_date: str) -> pd.DataFrame:
    import akshare as ak
    df=ak.stock_zh_a_spot_em()
    if df is None or df.empty: raise RuntimeError("AKShare全A实时行情为空")
    ren={"代码":"code","名称":"name","今开":"open","最新价":"close","最高":"high","最低":"low","昨收":"pre_close","涨跌额":"change","涨跌幅":"pct","成交量":"volume","成交额":"amount"}
    df=df.rename(columns=ren)
    for c in ren.values():
        if c not in df.columns: df[c]=float("nan") if c not in {"code","name"} else ""
    df["exchange"]=[normalize_exchange(str(c)) for c in df["code"]]
    # AKShare/东方财富全A快照成交量通常为手，成交额为元。
    df["volume"]=pd.to_numeric(df["volume"],errors="coerce")*100
    df["source"]="akshare"
    return validate(df,iso(trade_date))


def latest_open_day(token: str) -> str:
    now=datetime.now(ZoneInfo("Asia/Shanghai"))
    if token:
        import tushare as ts
        pro=ts.pro_api(token)
        start=(now.date()-timedelta(days=15)).strftime("%Y%m%d")
        end=now.strftime("%Y%m%d")
        cal=pro.trade_cal(exchange="SSE",start_date=start,end_date=end,is_open="1",fields="cal_date")
        if cal is not None and not cal.empty:
            dates=sorted(cal["cal_date"].astype(str))
            # 收盘前手动运行时不写入尚未完成的当天行情。
            if now.hour < 16 and dates and dates[-1]==end: dates=dates[:-1]
            if dates: return iso(dates[-1])
    # 无Token时退化为工作日推断，实际抓取仍会由数据完整性校验把关。
    d=now.date() if now.hour>=16 else now.date()-timedelta(days=1)
    while d.weekday()>=5: d-=timedelta(days=1)
    return d.isoformat()


def write_day(df: pd.DataFrame, trade_date: str, source: str) -> None:
    DAILY_DIR.mkdir(parents=True,exist_ok=True)
    rows=[]
    for row in df[COLUMNS].itertuples(index=False,name=None):
        vals=[]
        for v in row:
            if pd.isna(v): vals.append(None)
            elif isinstance(v,float): vals.append(round(v,6))
            else: vals.append(v)
        rows.append(vals)
    doc={"schema_version":1,"trade_date":trade_date,"source":source,"columns":COLUMNS,"rows":rows}
    raw=json.dumps(doc,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    path=DAILY_DIR/f"{trade_date}.json"
    path.write_bytes(raw)
    (DATA_DIR/"latest.json").write_bytes(raw)
    df.assign(trade_date=trade_date).to_csv(DATA_DIR/"latest.csv",index=False,encoding="utf-8-sig")
    manifest=load_manifest(); manifest.setdefault("days",{})[trade_date]={"rows":len(df),"source":source,"sha256":hashlib.sha256(raw).hexdigest()}
    manifest.setdefault("available_dates",[]).append(trade_date); manifest["source"]=source
    save_manifest(manifest)
    log(f"写入 {path.relative_to(ROOT)}，{len(df)}行，来源{source}")


def fetch_day(trade_date: str, token: str, allow_akshare: bool=True) -> tuple[pd.DataFrame,str]:
    errors=[]
    if token:
        try: return fetch_tushare(trade_date,token),"tushare"
        except Exception as e: errors.append(f"TuShare: {e}")
    if allow_akshare:
        try: return fetch_akshare_latest(trade_date),"akshare"
        except Exception as e: errors.append(f"AKShare: {e}")
    raise RuntimeError("；".join(errors) or "没有可用数据源")



def validate_with_baostock(df: pd.DataFrame, trade_date: str) -> None:
    """用BaoStock抽样核对未复权收盘价。校验源不可用时只记录警告，不中断更新。"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            log(f"BaoStock校验跳过：登录失败 {lg.error_msg}")
            return
        preferred = ["000001", "600000", "600519", "300750", "601318", "000333", "600036", "000858"]
        available = set(df["code"].astype(str))
        codes = [c for c in preferred if c in available][:6]
        mismatches=[]; checked=0
        close_map = dict(zip(df["code"].astype(str), pd.to_numeric(df["close"], errors="coerce")))
        for code in codes:
            market_code = ("sh." if code.startswith(("5","6","9")) else "sz.") + code
            rs = bs.query_history_k_data_plus(market_code, "date,code,close", start_date=trade_date, end_date=trade_date, frequency="d", adjustflag="3")
            if rs.error_code != "0":
                continue
            row = rs.get_row_data() if rs.next() else None
            if not row:
                continue
            checked += 1
            other = float(row[2]); primary=float(close_map[code])
            if abs(other-primary) > 0.02:
                mismatches.append(f"{code}:{primary}/{other}")
        bs.logout()
        if mismatches:
            log("BaoStock抽样差异警告：" + ", ".join(mismatches))
        else:
            log(f"BaoStock抽样校验完成：{checked}只，无明显差异")
    except Exception as e:
        log(f"BaoStock校验跳过：{e}")

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--date",default="auto",help="YYYY-MM-DD/ YYYYMMDD / auto")
    ap.add_argument("--force",action="store_true")
    args=ap.parse_args()
    token=os.getenv("TUSHARE_TOKEN","").strip()
    if not token:
        raise RuntimeError("必须在GitHub Actions Secret中配置TUSHARE_TOKEN，避免节假日被错误标记为交易日")
    trade_date=latest_open_day(token) if args.date=="auto" else iso(args.date)
    out=DAILY_DIR/f"{trade_date}.json"
    if out.exists() and not args.force:
        log(f"{trade_date}已存在，跳过。使用--force可覆盖")
        return 0
    df,source=fetch_day(trade_date,token,allow_akshare=True)
    validate_with_baostock(df, trade_date)
    write_day(df,trade_date,source)
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as e:
        log(f"失败：{e}")
        raise
