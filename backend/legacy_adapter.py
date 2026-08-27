"""Compatibility layer for porting validated V1 analytics into V2.
The copied V1 modules are retained verbatim for auditability. This adapter
normalizes V2 data before invoking them. Do not silently change V1 thresholds.
"""
import pandas as pd

def eod_frame(rows):
    rec=[]
    for z in rows:
        if isinstance(z,(list,tuple)):
            rec.append({'ts':z[0],'close':z[1],'volume':z[2] if len(z)>2 else 0,'open':z[3] if len(z)>3 else None})
        else:
            rec.append({'ts':z.get('time',z.get('timestamp')),'close':z.get('close',z.get('price')),'volume':z.get('volume',0),'open':z.get('open')})
    df=pd.DataFrame(rec)
    if len(df):
        df['date']=pd.to_datetime(df['ts'],unit='s',errors='coerce')
        df=df.sort_values('date').reset_index(drop=True)
    return df
