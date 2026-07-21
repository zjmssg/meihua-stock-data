#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, time
from datetime import datetime
import pandas as pd
from update_market_data import fetch_tushare, write_day, iso, ymd, DAILY_DIR, log

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--start',required=True)
    ap.add_argument('--end',required=True)
    ap.add_argument('--force',action='store_true')
    args=ap.parse_args()
    token=os.getenv('TUSHARE_TOKEN','').strip()
    if not token: raise RuntimeError('历史回填必须配置GitHub Secret：TUSHARE_TOKEN')
    import tushare as ts
    pro=ts.pro_api(token)
    cal=pro.trade_cal(exchange='SSE',start_date=ymd(args.start),end_date=ymd(args.end),is_open='1',fields='cal_date')
    if cal is None or cal.empty: raise RuntimeError('所选范围没有交易日')
    dates=sorted(cal['cal_date'].astype(str))
    for i,d in enumerate(dates,1):
        date=iso(d); path=DAILY_DIR/f'{date}.json'
        if path.exists() and not args.force:
            log(f'[{i}/{len(dates)}] {date} 已存在，跳过'); continue
        for attempt in range(1,4):
            try:
                df=fetch_tushare(date,token); write_day(df,date,'tushare'); break
            except Exception as e:
                if attempt==3: raise
                log(f'{date} 第{attempt}次失败：{e}，稍后重试'); time.sleep(attempt*3)
        time.sleep(0.35)

if __name__=='__main__': main()
