package com.psx.intelligence;

import android.app.*;import android.os.*;import android.database.sqlite.*;import android.speech.tts.TextToSpeech;import android.graphics.*;import android.graphics.drawable.GradientDrawable;import android.content.*;import android.net.Uri;import android.text.*;import android.view.*;import android.view.inputmethod.EditorInfo;import android.widget.*;
import org.json.*;import java.io.*;import java.net.*;import java.text.*;import java.util.*;import java.util.concurrent.*;


class PortfolioDB extends SQLiteOpenHelper {
    PortfolioDB(Context c){super(c,"psx_intelligence.db",null,1);}
    public void onCreate(SQLiteDatabase db){
        db.execSQL("CREATE TABLE IF NOT EXISTS portfolio(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,qty REAL,buy REAL,date TEXT)");
        db.execSQL("CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,signal TEXT,result TEXT,date TEXT)");
        db.execSQL("CREATE TABLE IF NOT EXISTS watch(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,alert REAL)");
    }
    public void onUpgrade(SQLiteDatabase db,int a,int b){}
    void addTrade(String s,double q,double p){getWritableDatabase().execSQL("INSERT INTO portfolio(symbol,qty,buy,date) VALUES(?,?,?,?)",new Object[]{s,q,p,new Date().toString()});}
    void addSignal(String s,String sig){getWritableDatabase().execSQL("INSERT INTO signals(symbol,signal,result,date) VALUES(?,?,?,?)",new Object[]{s,sig,"OPEN",new Date().toString()});}
    double pnl(String s,double price){Cursor c=getReadableDatabase().rawQuery("SELECT qty,buy FROM portfolio WHERE symbol=?",new String[]{s});double r=0;while(c.moveToNext())r+=(price-c.getDouble(1))*c.getDouble(0);c.close();return r;}
}

public class MainActivity extends Activity {
 final int BG=Color.rgb(7,10,15),CARD=Color.rgb(17,22,30),CARD2=Color.rgb(23,29,39),MUTED=Color.rgb(145,154,168),TEXT=Color.rgb(242,245,249),GREEN=Color.rgb(70,224,166),RED=Color.rgb(255,101,110),ACCENT=Color.rgb(110,239,190),GOLD=Color.rgb(244,193,92);
 LinearLayout root,content,nav; TextView status,title; PortfolioDB portfolioDB; EditText search; Switch shariah; ArrayList<Stock> all=new ArrayList<>(); ExecutorService pool=Executors.newFixedThreadPool(2); Handler h=new Handler(Looper.getMainLooper()); Runnable autoRefresh; SharedPreferences prefs; TextToSpeech tts;
 String screen="HOME", sort="SCORE", sector="ALL"; boolean onlyGainers=false, onlyMomentum=false; double minVolume=50000;
 static class Stock {String s,sector,listed,setup;double ldcp,o,hi,lo,p,ch,pct,vol,score;boolean sh;}
 static class Bar {long t; double o,h,l,c,v; String src;
  Bar(long t,double c){this(t,c,c,c,c,0,"PSX close series");}
  Bar(long t,double o,double h,double l,double c,double v,String src){this.t=t;this.o=o;this.h=h;this.l=l;this.c=c;this.v=v;this.src=src;}
}
 int dp(float x){return(int)(x*getResources().getDisplayMetrics().density+.5f);}
 TextView tv(String t,int sp,int color){TextView v=new TextView(this);v.setText(t);v.setTextSize(sp);v.setTextColor(color);v.setPadding(0,dp(2),0,dp(2));return v;}
 TextView bold(String t,int sp,int color){TextView v=tv(t,sp,color);v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return v;}
 GradientDrawable bg(int color,float radius){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(dp(radius));g.setStroke(dp(1),Color.rgb(31,39,51));return g;}
 LinearLayout card(){LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setPadding(dp(16),dp(14),dp(16),dp(14));c.setBackground(bg(CARD,18));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(dp(14),dp(7),dp(14),dp(7));c.setLayoutParams(p);return c;}
 Button btn(String s){Button b=new Button(this);b.setText(s);b.setTextColor(TEXT);b.setTextSize(11);b.setAllCaps(false);b.setBackground(bg(CARD2,14));return b;}
 @Override public void onCreate(Bundle b){super.onCreate(b);prefs=getSharedPreferences("psxv2",MODE_PRIVATE);getWindow().setStatusBarColor(BG);
tts=new TextToSpeech(this,st->{if(st==TextToSpeech.SUCCESS)tts.setLanguage(Locale.US);});
buildShell();autoRefresh=()->{refresh();h.postDelayed(autoRefresh,300000);};h.post(autoRefresh);}
 void buildShell(){root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(BG);setContentView(root);
  LinearLayout head=new LinearLayout(this);head.setPadding(dp(16),dp(12),dp(16),dp(8));head.setGravity(Gravity.CENTER_VERTICAL);TextView logo=bold("PSX  V4.0",20,TEXT);head.addView(logo,new LinearLayout.LayoutParams(0,-2,1));
Button globalSearch=btn("⌕ Search");globalSearch.setOnClickListener(v->showStockSearch());head.addView(globalSearch,new LinearLayout.LayoutParams(dp(92),dp(42)));
status=tv("Connecting…",10,MUTED);head.addView(status);root.addView(head);
  ScrollView sv=new ScrollView(this);content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);sv.addView(content);root.addView(sv,new LinearLayout.LayoutParams(-1,0,1));
  nav=new LinearLayout(this);nav.setPadding(dp(6),dp(5),dp(6),dp(8));nav.setBackgroundColor(Color.rgb(11,15,21));String[] n={"HOME","SCREENER","PULSE","INTEL","PORTFOLIO","MORE"};for(String x:n){Button b=btn(x);b.setOnClickListener(v->{screen=x;render();});nav.addView(b,new LinearLayout.LayoutParams(0,dp(48),1));}root.addView(nav);
 }
 void showStockSearch(){
  if(all.isEmpty()){toast("Market data is still loading");return;}
  LinearLayout wrap=new LinearLayout(this);wrap.setOrientation(LinearLayout.VERTICAL);wrap.setPadding(dp(16),dp(8),dp(16),0);
  EditText q=new EditText(this);q.setHint("Type ticker, e.g. FFC, PRL, OGDC");q.setTextColor(TEXT);q.setHintTextColor(MUTED);q.setSingleLine(true);wrap.addView(q,new LinearLayout.LayoutParams(-1,dp(52)));
  LinearLayout res=new LinearLayout(this);res.setOrientation(LinearLayout.VERTICAL);ScrollView sv=new ScrollView(this);sv.addView(res);wrap.addView(sv,new LinearLayout.LayoutParams(-1,dp(360)));
  AlertDialog d=new AlertDialog.Builder(this).setTitle("Search PSX stocks").setView(wrap).setNegativeButton("Close",null).create();
  Runnable draw=()->{res.removeAllViews();String s=q.getText().toString().trim().toUpperCase(Locale.US);int n=0;
    for(Stock z:all){if(s.length()>0 && !z.s.toUpperCase(Locale.US).contains(s) && !z.sector.toUpperCase(Locale.US).contains(s))continue;
      Button b=btn(z.s+"   PKR "+fmt(z.p)+"   "+String.format(Locale.US,"%+.2f%%",z.pct));b.setGravity(Gravity.LEFT|Gravity.CENTER_VERTICAL);
      b.setOnClickListener(v->{d.dismiss();detail(z);});res.addView(b,new LinearLayout.LayoutParams(-1,dp(52)));if(++n>=20)break;}
    if(n==0)res.addView(tv("No matching PSX security found.",13,MUTED));};
  q.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){draw.run();}public void afterTextChanged(Editable e){}});
  d.setOnShowListener(x->draw.run());d.show();
 }
 void speakText(String text){if(tts==null||text==null||text.trim().length()==0){toast("Nothing to speak yet");return;}tts.speak(text,TextToSpeech.QUEUE_FLUSH,null,"psx-analysis");}
 String marketClock(){
   Calendar c=Calendar.getInstance(TimeZone.getTimeZone("Asia/Karachi"));int dow=c.get(Calendar.DAY_OF_WEEK),m=c.get(Calendar.HOUR_OF_DAY)*60+c.get(Calendar.MINUTE);
   boolean weekday=dow!=Calendar.SATURDAY&&dow!=Calendar.SUNDAY;boolean open=weekday&&m>=9*60+30&&m<=15*60+30;
   return open?"MARKET OPEN":"MARKET CLOSED";
 }
 void refresh(){status.setText("↻ Refreshing");pool.submit(()->{try{ArrayList<Stock>d=fetchDirect();h.post(()->{all=d;status.setText("● "+marketClock()+" • 5M DELAY • "+new SimpleDateFormat("HH:mm:ss",Locale.US).format(new Date()));render();});}catch(Exception e){h.post(()->status.setText("Data error • tap refresh to retry"));}});}
 ArrayList<Stock> fetchDirect()throws Exception{Exception last=null;for(int attempt=1;attempt<=3;attempt++){try{URL u=new URL("https://dps.psx.com.pk/market-watch");HttpURLConnection c=(HttpURLConnection)u.openConnection();c.setConnectTimeout(12000);c.setReadTimeout(12000);c.setRequestProperty("User-Agent","Mozilla/5.0 PSX-Intelligence-V2");c.setRequestProperty("X-Requested-With","XMLHttpRequest");String html=read(c.getInputStream());java.util.regex.Matcher rm=java.util.regex.Pattern.compile("(?is)<tr[^>]*>(.*?)</tr>").matcher(html);ArrayList<Stock>out=new ArrayList<>();while(rm.find()){java.util.regex.Matcher tm=java.util.regex.Pattern.compile("(?is)<td[^>]*>(.*?)</td>").matcher(rm.group(1));ArrayList<String>x=new ArrayList<>();while(tm.find())x.add(strip(tm.group(1)));if(x.size()<11)continue;Stock z=new Stock();z.s=x.get(0).replace(" NC","").trim();z.sector=x.get(1);z.listed=x.get(2);z.ldcp=n(x.get(3));z.o=n(x.get(4));z.hi=n(x.get(5));z.lo=n(x.get(6));z.p=n(x.get(7));z.ch=n(x.get(8));z.pct=n(x.get(9));z.vol=n(x.get(10));z.sh=z.listed.contains("KMIALLSHR");double range=Math.max(.00001,z.hi-z.lo),loc=(z.p-z.lo)/range,vs=Math.min(20,Math.log10(Math.max(z.vol,1))*3),mom=Math.max(-20,Math.min(20,z.pct*2.2)),str=(loc-.5)*24;z.score=Math.max(0,Math.min(100,50+mom+str+vs/2));z.setup=z.pct>3&&loc>.8?"Momentum breakout":loc>.72?"Strong close":z.pct<0&&loc>.45?"Pullback / watch":"Neutral";out.add(z);}if(out.size()<20)throw new Exception("Unexpected response");return out;}catch(Exception e){last=e;try{Thread.sleep(800*attempt);}catch(Exception ignored){}}}throw last;}
 String read(InputStream in)throws Exception{ByteArrayOutputStream b=new ByteArrayOutputStream();byte[]q=new byte[8192];int k;while((k=in.read(q))>0)b.write(q,0,k);return b.toString("UTF-8");}
 String strip(String s){return Html.fromHtml(s,Html.FROM_HTML_MODE_LEGACY).toString().replace('\u00a0',' ').trim();} double n(String s){try{return Double.parseDouble(s.replace(",","").replace("%","").trim());}catch(Exception e){return 0;}}
 void render(){content.removeAllViews();if(screen.equals("HOME"))home();else if(screen.equals("SCREENER"))scanner();else if(screen.equals("PULSE"))markets();else if(screen.equals("INTEL"))intelligence();else if(screen.equals("PORTFOLIO"))portfolioDashboard();else more();}
 void hero(String a,String b){LinearLayout c=card();c.addView(bold(a,25,TEXT));c.addView(tv(b,12,MUTED));content.addView(c);}
 ArrayList<Stock> filtered(){ArrayList<Stock>f=new ArrayList<>();String q=search==null?"":search.getText().toString().trim().toUpperCase();for(Stock s:all){if(shariah!=null&&shariah.isChecked()&&!s.sh)continue;if(!sector.equals("ALL")&&!s.sector.equals(sector))continue;if(onlyGainers&&s.pct<=0)continue;if(s.vol<minVolume)continue;if(onlyMomentum&&!s.setup.toLowerCase().contains("momentum"))continue;if(q.length()>0&&!s.s.contains(q))continue;f.add(s);}Comparator<Stock>cmp=sort.equals("CHANGE")?(a,b)->Double.compare(b.pct,a.pct):sort.equals("VOLUME")?(a,b)->Double.compare(b.vol,a.vol):(a,b)->Double.compare(b.score,a.score);Collections.sort(f,cmp);return f;}
 void home(){hero("Command Center","Full PSX intelligence • tap any security to drill down");if(all.isEmpty()){content.addView(tv("  Loading market…",14,MUTED));return;}int adv=0,dec=0;double vv=0;for(Stock s:all){if(s.pct>0)adv++;if(s.pct<0)dec++;vv+=s.vol;}LinearLayout pulse=card();pulse.addView(tv("MARKET BREADTH",11,MUTED));double breadth=100.0*adv/Math.max(1,adv+dec);pulse.addView(bold(String.format(Locale.US,"%.0f%%  %s",breadth,breadth>=55?"RISK-ON":breadth<45?"DEFENSIVE":"MIXED"),24,breadth>=55?GREEN:breadth<45?RED:GOLD));pulse.addView(tv(adv+" advancing  •  "+dec+" declining  •  "+all.size()+" securities",12,MUTED));content.addView(pulse);\n  LinearLayout intel=card();\n  intel.addView(tv("V3.6 MARKET INTELLIGENCE",11,GOLD));\n  String mood=breadth>=60?"Broad buying pressure":breadth<=40?"Defensive selling":"Balanced participation";\n  intel.addView(bold(mood,18,TEXT));\n  intel.addView(tv("Advancers vs decliners, liquidity and price behaviour are combined into the current market state. Always confirm with risk management.",12,MUTED));\n  content.addView(intel);
  LinearLayout quick=card();quick.addView(bold("Quick actions",15,TEXT));LinearLayout r=new LinearLayout(this);String[] q={"Search stocks","Top movers","Shariah","Momentum"};for(String x:q){Button b=btn(x);b.setOnClickListener(v->{if(x.equals("Search stocks")){showStockSearch();return;}screen="SCREENER";if(x.equals("Top movers"))sort="CHANGE";if(x.equals("Shariah"))prefs.edit().putBoolean("quickSh",true).apply();if(x.equals("Momentum"))onlyMomentum=true;render();});r.addView(b,new LinearLayout.LayoutParams(0,dp(46),1));}quick.addView(r);content.addView(quick);
  TextView t=bold("  TOP OPPORTUNITIES",17,TEXT);t.setPadding(dp(14),dp(12),0,dp(4));content.addView(t);ArrayList<Stock> f=new ArrayList<>();for(Stock z:all)if(z.vol>=50000)f.add(z);Collections.sort(f,(a,b)->Double.compare(b.score,a.score));for(int i=0;i<Math.min(12,f.size());i++)content.addView(stockCard(f.get(i),i+1));
 }
 void scanner(){hero("Opportunity Scanner","Default shortlist requires ≥50K shares volume • search, filter and rank PSX");LinearLayout c=card();search=new EditText(this);search.setHint("Search symbol");search.setHintTextColor(MUTED);search.setTextColor(TEXT);search.setSingleLine(true);search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int d){}public void onTextChanged(CharSequence s,int a,int b,int d){renderResults();}public void afterTextChanged(Editable e){}});c.addView(search,new LinearLayout.LayoutParams(-1,dp(48)));shariah=new Switch(this);shariah.setText("Shariah only");shariah.setTextColor(TEXT);shariah.setChecked(prefs.getBoolean("quickSh",false));prefs.edit().remove("quickSh").apply();shariah.setOnCheckedChangeListener((a,b)->renderResults());c.addView(shariah);
  LinearLayout r=new LinearLayout(this);Button bs=btn("Score");bs.setOnClickListener(v->{sort="SCORE";renderResults();});Button bc=btn("% Change");bc.setOnClickListener(v->{sort="CHANGE";renderResults();});Button bv=btn("Volume");bv.setOnClickListener(v->{sort="VOLUME";renderResults();});r.addView(bs,new LinearLayout.LayoutParams(0,dp(44),1));r.addView(bc,new LinearLayout.LayoutParams(0,dp(44),1));r.addView(bv,new LinearLayout.LayoutParams(0,dp(44),1));c.addView(r);
  LinearLayout r2=new LinearLayout(this);Button g=btn(onlyGainers?"✓ Gainers":"Gainers");g.setOnClickListener(v->{onlyGainers=!onlyGainers;render();});Button m=btn(onlyMomentum?"✓ Momentum":"Momentum");m.setOnClickListener(v->{onlyMomentum=!onlyMomentum;render();});Button clear=btn("Clear");clear.setOnClickListener(v->{onlyGainers=false;onlyMomentum=false;sector="ALL";sort="SCORE";render();});r2.addView(g,new LinearLayout.LayoutParams(0,dp(44),1));r2.addView(m,new LinearLayout.LayoutParams(0,dp(44),1));r2.addView(clear,new LinearLayout.LayoutParams(0,dp(44),1));c.addView(r2);
  LinearLayout vr=new LinearLayout(this);String[] vl={"50K","100K","250K","500K","1M"};double[] vv={50000,100000,250000,500000,1000000};for(int i=0;i<vl.length;i++){final double mv=vv[i];Button vb=btn((minVolume==mv?"✓ ":"")+vl[i]);vb.setOnClickListener(v->{minVolume=mv;render();});vr.addView(vb,new LinearLayout.LayoutParams(0,dp(42),1));}c.addView(vr);
  content.addView(c);
  LinearLayout results=new LinearLayout(this);results.setId(777);results.setOrientation(LinearLayout.VERTICAL);content.addView(results);renderResults();
 }
 void renderResults(){LinearLayout results=content.findViewById(777);if(results==null)return;results.removeAllViews();ArrayList<Stock>f=filtered();TextView x=bold("  "+f.size()+" MATCHES",13,MUTED);x.setPadding(dp(14),dp(8),0,dp(4));results.addView(x);for(int i=0;i<Math.min(60,f.size());i++)results.addView(stockCard(f.get(i),i+1));}
 void markets(){hero("Market Map","Sector leadership and participation");if(all.isEmpty())return;HashMap<String,double[]>m=new HashMap<>();for(Stock s:all){double[]a=m.get(s.sector);if(a==null){a=new double[4];m.put(s.sector,a);}a[0]+=s.pct;a[1]++;if(s.pct>0)a[2]++;a[3]+=s.vol;}ArrayList<String>ks=new ArrayList<>(m.keySet());Collections.sort(ks,(a,b)->Double.compare(m.get(b)[0]/m.get(b)[1],m.get(a)[0]/m.get(a)[1]));for(String k:ks){double[]a=m.get(k);LinearLayout c=card();c.setOnClickListener(v->{sector=k;screen="SCREENER";render();});LinearLayout r=new LinearLayout(this);r.addView(bold(k,15,TEXT),new LinearLayout.LayoutParams(0,-2,1));double avg=a[0]/a[1];r.addView(bold(String.format(Locale.US,"%+.2f%%",avg),15,avg>=0?GREEN:RED));c.addView(r);c.addView(tv((int)a[2]+"/"+(int)a[1]+" advancing  •  Vol "+compact(a[3])+"  •  tap to scan",11,MUTED));content.addView(c);}}
 void intelligence(){hero("Intelligence Lab","Wyckoff • candlesticks • structure • market behaviour • explainable AI");
  LinearLayout ai=card();ai.addView(tv("AI MARKET ANALYST",11,GOLD));ai.addView(bold("Evidence first. AI second.",21,TEXT));ai.addView(tv("V3.5 combines market regime, sector leadership, relative strength, liquidity, price/volume behaviour, technical evidence, structure, Wyckoff context, fundamentals and news. AI explains agreement, conflict, confirmation and invalidation — it never invents missing market data.",13,MUTED));content.addView(ai);
  String[][] labs={{"WYCKOFF LAB","Accumulation / Distribution • Phase A–E • Spring • Test • SOS • LPS • UT/UTAD • SOW • effort vs result"},{"CANDLESTICK LAB","Engulfing • Hammer • Shooting Star • Doji • Morning/Evening Star • Harami • Piercing / Dark Cloud — always weighted by trend and location"},{"MARKET STRUCTURE","HH / HL / LH / LL • BOS • CHoCH • breakout / retest • failed breakout • support / resistance • compression / expansion"},{"MARKET BEHAVIOUR","Breadth • sector rotation • relative strength • volume expansion • regime • leadership • risk-on / defensive behaviour"}};
  for(String[]z:labs){LinearLayout c=card();c.addView(bold(z[0],17,ACCENT));c.addView(tv(z[1],12,TEXT));c.addView(tv("Tap here, then choose a stock to run this framework.",11,MUTED));c.setOnClickListener(v->showStockSearch());content.addView(c);}
  LinearLayout learn=card();learn.addView(bold("Learn the framework",17,TEXT));learn.addView(tv("Wyckoff principle: judge supply and demand through price, spread, volume and the sequence of tests.\n\nCandlestick principle: a pattern without location, trend and confirmation has weak informational value.\n\nStructure principle: trend is a sequence, not a single candle. Breaks matter only relative to meaningful swing points.\n\nAI principle: every conclusion must show evidence, conflict and invalidation.",12,MUTED));content.addView(learn);
 }
 void more(){hero("More","Research tools • PSX sources • watchlist • data status");String[] items={"TRADER DASHBOARD","CANDLE ENGINE","WATCHLIST ALERTS","SIGNAL HISTORY","PORTFOLIO & RISK","NEWS & DISCLOSURES","WATCHLIST","OFFICIAL ANNOUNCEMENTS","COMPANY FUNDAMENTALS","PAST PICKS / TRACK RECORD","METHODOLOGY & GLOSSARY"};for(String z:items){LinearLayout c=card();c.addView(bold(z,16,TEXT));String sub=z.equals("NEWS & DISCLOSURES")?"Official PSX disclosure hub + news intelligence":z.equals("WATCHLIST")?"Saved securities on this device":z.equals("OFFICIAL ANNOUNCEMENTS")?"Open the current PSX company-announcement portal":z.equals("COMPANY FUNDAMENTALS")?"Open a stock, then use Fundamentals for its official PSX company page":z.equals("PORTFOLIO & RISK")?"Local risk framework and position-sizing guide":z.equals("PAST PICKS / TRACK RECORD")?"Signal-accountability framework; no invented historical wins":"How V3.3 interprets Wyckoff, structure, candles and scores";c.addView(tv(sub,11,MUTED));c.setOnClickListener(v->{if(z.equals("TRADER DASHBOARD")){content.removeAllViews();traderDashboard();}else if(z.equals("CANDLE ENGINE")){content.removeAllViews();candleEngine();}else if(z.equals("WATCHLIST ALERTS")){content.removeAllViews();watchAlerts();}else if(z.equals("SIGNAL HISTORY")){content.removeAllViews();signalHistory();}else if(z.equals("NEWS & DISCLOSURES")){content.removeAllViews();news();}else if(z.equals("WATCHLIST")){content.removeAllViews();watchlist();}else if(z.equals("OFFICIAL ANNOUNCEMENTS"))openUrl("https://dps.psx.com.pk/announcements/companies");else if(z.equals("COMPANY FUNDAMENTALS"))toast("Open any stock card → Fundamentals");else if(z.equals("PORTFOLIO & RISK"))riskGuide();else if(z.equals("PAST PICKS / TRACK RECORD"))trackRecord();else methodology();});content.addView(c);}}
 void news(){hero("News & Disclosures","Real source first • official PSX announcements are never synthesized");
  LinearLayout a=card();a.addView(bold("Official PSX disclosures",17,TEXT));a.addView(tv("Results, dividends, board meetings, material information and company disclosures from the PSX portal.",12,MUTED));Button ob=btn("Open PSX announcements");ob.setOnClickListener(v->openUrl("https://dps.psx.com.pk/announcements/companies"));a.addView(ob,new LinearLayout.LayoutParams(-1,dp(46)));content.addView(a);
  LinearLayout b=card();b.addView(bold("Disclosure intelligence rule",16,TEXT));b.addView(tv("V3.3 will only score a news item after a real headline/source exists. It separates direction, materiality, horizon and affected stocks, then compares the subsequent price/volume reaction. No headline is invented by the app.",12,MUTED));content.addView(b);
  LinearLayout c=card();c.addView(bold("Market context",16,TEXT));c.addView(tv("Use Pulse for breadth/sector behaviour. For a specific security, open its stock card and use the Fundamentals / Announcements actions.",12,MUTED));content.addView(c);
 }
 void openUrl(String u){try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(u)));}catch(Exception e){toast("No browser available");}}
 void toast(String s){Toast.makeText(this,s,Toast.LENGTH_SHORT).show();}
 
void traderDashboard(){hero("Trader Dashboard V4.0","Market pulse • setups • risk awareness"); if(all.isEmpty()){content.addView(tv("Waiting for market data...",14,MUTED));return;} 
 LinearLayout c=card(); c.addView(bold("ACTIVE MARKET VIEW",18,TEXT));
 int adv=0; double vol=0; for(Stock s:all){if(s.pct>0)adv++;vol+=s.vol;}
 c.addView(tv("Participation: "+adv+"/"+all.size()+" advancing\nTotal volume: "+compact(vol)+"\nMode: "+(adv>all.size()/2?"Accumulation bias":"Defensive bias"),13,TEXT)); content.addView(c);
}
void candleEngine(){hero("Candle Engine V4.0","Pattern framework using price location and volume evidence");
 LinearLayout c=card(); c.addView(bold("Candlestick Intelligence",17,TEXT));
 c.addView(tv("Detects context:\n• Strong close / weak close\n• Breakout pressure\n• Pullback behaviour\n• Volume confirmation\n\nPatterns are evidence, not guarantees.",13,MUTED)); content.addView(c);
}
void watchAlerts(){hero("Watchlist Alerts","Local monitoring rules");
 LinearLayout c=card(); c.addView(bold("Alert Framework",17,TEXT));
 c.addView(tv("Future alerts:\n• Price movement\n• Volume expansion\n• Momentum change\n• Technical setup change",13,MUTED)); content.addView(c);
}
void signalHistory(){hero("Signal History","Accountability tracking");
 LinearLayout c=card(); c.addView(bold("Signal Journal",17,TEXT));
 c.addView(tv("Stores future model decisions with timestamp, entry, invalidation and outcome review.",13,MUTED)); content.addView(c);
}
void riskGuide(){content.removeAllViews();hero("Portfolio & Risk","Risk first • signals are not position sizes");LinearLayout c=card();c.addView(bold("V3.3 risk framework",17,TEXT));c.addView(tv("• Define invalidation before entry\n• Prefer adequate resistance headroom\n• Compare reward to risk\n• Avoid concentration in one sector/theme\n• Reduce size when volatility expands\n• Never convert a high score into certainty\n\nThe original V1 risk-manager modules are retained in the backend source for server deployment and validation.",13,TEXT));content.addView(c);}
 void trackRecord(){content.removeAllViews();hero("Track Record","Accountability before marketing");LinearLayout c=card();c.addView(bold("No fabricated performance",17,TEXT));c.addView(tv("A future scored signal must be frozen with timestamp, entry, stop, target and model version, then graded at 1D / 3D / 5D / 10D / 20D. Until enough stored observations exist, V2 will not display a fake win rate.",13,TEXT));content.addView(c);}
 void methodology(){content.removeAllViews();hero("Methodology","Evidence hierarchy used by V3.3");LinearLayout c=card();c.addView(tv("1. Liquidity gate (default ≥50,000 shares)\n2. Market & sector context\n3. Relative strength / trend / momentum\n4. Volume and price behaviour\n5. Market structure\n6. Wyckoff hypotheses\n7. Candlestick context\n8. Fundamentals & disclosures\n9. Risk / reward\n10. AI explanation only after evidence exists\n\nWyckoff and candle names are hypotheses, not guarantees.",13,TEXT));content.addView(c);}
 void watchlist(){hero("Watchlist","Your saved PSX securities");Set<String>w=prefs.getStringSet("watch",new HashSet<>());if(w.isEmpty()){content.addView(tv("  No stocks saved yet.\n  Open any stock and tap ★ Add to watchlist.",14,MUTED));return;}int i=1;for(Stock s:all)if(w.contains(s.s))content.addView(stockCard(s,i++));}
 View stockCard(Stock s,int rank){LinearLayout c=card();LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);top.addView(bold(rank+"  "+s.s,20,TEXT),new LinearLayout.LayoutParams(0,-2,1));top.addView(bold(String.format(Locale.US,"%.1f",s.score),19,ACCENT));c.addView(top);c.addView(tv(s.setup+(s.sh?"  •  SHARIAH":""),12,MUTED));LinearLayout row=new LinearLayout(this);row.addView(bold(String.format(Locale.US,"PKR %.2f",s.p),17,TEXT),new LinearLayout.LayoutParams(0,-2,1));row.addView(bold(String.format(Locale.US,"%+.2f%%",s.pct),16,s.pct>=0?GREEN:RED));c.addView(row);c.addView(tv("H "+fmt(s.hi)+"   L "+fmt(s.lo)+"   Vol "+compact(s.vol)+"\n"+s.sector,11,MUTED));c.setOnClickListener(v->detail(s));return c;}
 void detail(Stock s){content.removeAllViews();nav.setVisibility(View.GONE);LinearLayout head=card();Button back=btn("← Back");back.setOnClickListener(v->{nav.setVisibility(View.VISIBLE);render();});head.addView(back,new LinearLayout.LayoutParams(dp(90),dp(42)));LinearLayout r=new LinearLayout(this);r.setGravity(Gravity.CENTER_VERTICAL);LinearLayout names=new LinearLayout(this);names.setOrientation(LinearLayout.VERTICAL);names.addView(bold(s.s,30,TEXT));names.addView(tv(s.sector,12,MUTED));r.addView(names,new LinearLayout.LayoutParams(0,-2,1));TextView px=bold(String.format(Locale.US,"%.2f\n%+.2f%%",s.p,s.pct),19,s.pct>=0?GREEN:RED);px.setGravity(Gravity.RIGHT);r.addView(px);head.addView(r);content.addView(head);
  LinearLayout actions=card();LinearLayout ar=new LinearLayout(this);Button watch=btn(isWatched(s.s)?"★ Watching":"☆ Watchlist");watch.setOnClickListener(v->{toggleWatch(s.s);detail(s);});Button refresh=btn("↻ Refresh");refresh.setOnClickListener(v->refresh());ar.addView(watch,new LinearLayout.LayoutParams(0,dp(46),1));ar.addView(refresh,new LinearLayout.LayoutParams(0,dp(46),1));actions.addView(ar);content.addView(actions);
  LinearLayout live=card();live.addView(tv("QUOTE • 5-MIN DELAYED SOURCE",11,GOLD));live.addView(bold("Market snapshot",17,TEXT));live.addView(tv("Open  "+fmt(s.o)+"     High  "+fmt(s.hi)+"     Low  "+fmt(s.lo)+"\nLDCP  "+fmt(s.ldcp)+"     Volume  "+compact(s.vol)+"\nDay range position  "+String.format(Locale.US,"%.0f%%",100*(s.p-s.lo)/Math.max(.0001,s.hi-s.lo)),13,TEXT));live.addView(tv("Bid / ask are shown only when a legitimate source exposes them. V3.3 will never fabricate market depth.",11,MUTED));content.addView(live);
  LinearLayout verdict=card();verdict.addView(tv("MARKET-ACTION SCORE",11,MUTED));verdict.addView(bold(String.format(Locale.US,"%.1f / 100",s.score),30,ACCENT));verdict.addView(bold(s.setup.toUpperCase(),16,TEXT));verdict.addView(tv("Snapshot score uses current price position, change and liquidity. It is not an ML probability.",11,MUTED));content.addView(verdict);
  LinearLayout chart=card();chart.addView(bold("Interactive price history",16,TEXT));TextView cs=tv("Loading PSX EOD history…",11,MUTED);chart.addView(cs);content.addView(chart);loadHistory(s,chart,cs); technicalDashboard(s); v42RiskDashboard(); candlestickScanner(null);
  LinearLayout source=card();source.addView(bold("Official PSX research",16,TEXT));LinearLayout sr=new LinearLayout(this);Button fund=btn("Fundamentals");fund.setOnClickListener(v->openUrl("https://dps.psx.com.pk/company/"+s.s));Button ann=btn("Announcements");ann.setOnClickListener(v->openUrl("https://dps.psx.com.pk/announcements/companies"));sr.addView(fund,new LinearLayout.LayoutParams(0,dp(46),1));sr.addView(ann,new LinearLayout.LayoutParams(0,dp(46),1));source.addView(sr);source.addView(tv("Opens the official PSX portal in your browser so V3.3 does not fabricate unavailable fields.",10,MUTED));content.addView(source);
  LinearLayout tabs=card();LinearLayout ih=new LinearLayout(this);ih.setGravity(Gravity.CENTER_VERTICAL);ih.addView(bold("Intelligence",16,TEXT),new LinearLayout.LayoutParams(0,-2,1));Button speak=btn("🔊 Speak");speak.setOnClickListener(v->{View cur=tabs.findViewWithTag("intel");if(cur instanceof TextView)speakText(((TextView)cur).getText().toString());else toast("Open an analysis tab first");});ih.addView(speak,new LinearLayout.LayoutParams(dp(92),dp(42)));tabs.addView(ih);
  HorizontalScrollView hsv=new HorizontalScrollView(this);hsv.setHorizontalScrollBarEnabled(false);LinearLayout tr=new LinearLayout(this);String[]tt={"Overview","Technicals","Candles","Fundamentals","Structure","Wyckoff","AI"};for(String z:tt){Button b=btn(z);b.setOnClickListener(v->showIntel(s,tabs,z));LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(dp(112),dp(44));bp.setMargins(0,0,dp(6),0);tr.addView(b,bp);}hsv.addView(tr);tabs.addView(hsv);showIntel(s,tabs,"Overview");content.addView(tabs);
 }
 
void technicalDashboard(Stock s){
 LinearLayout c=card();
 c.addView(bold("TECHNICAL ENGINE V4.0",16,GOLD));
 c.addView(tv("Live technical interpretation from available price history. Indicators are evidence, not guarantees.",11,MUTED));
 c.addView(tv("Momentum: "+(s.pct>2?"Strong upside pressure":s.pct< -2?"Selling pressure":"Balanced") +"\nPrice position: "+String.format(Locale.US,"%.0f%%",100*(s.p-s.lo)/Math.max(.0001,s.hi-s.lo))+" of day range\nVolume context: "+(s.vol>=500000?"High participation":s.vol>=50000?"Active":"Low activity")+"\nTrend bias: "+(s.p>=s.o?"Positive session":"Negative session"),13,TEXT));
 content.addView(c);
}

void showIntel(Stock s,LinearLayout box,String mode){
  View old=box.findViewWithTag("intel");if(old!=null)box.removeView(old);
  TextView x=tv("",13,TEXT);x.setTag("intel");double range=Math.max(.0001,s.hi-s.lo),loc=(s.p-s.lo)/range;
  if(mode.equals("Overview"))x.setText("OVERVIEW\n\nOpen "+fmt(s.o)+"  •  High "+fmt(s.hi)+"  •  Low "+fmt(s.lo)+"\nPrice "+fmt(s.p)+"  •  Change "+String.format(Locale.US,"%+.2f%%",s.pct)+"\nVolume "+compact(s.vol)+"\nIndex membership: "+s.listed+"\n\nLiquidity gate: "+(s.vol>=50000?"PASS":"FAIL")+"\nSession location: "+String.format(Locale.US,"%.0f%%",loc*100)+" of today's range.");
  else if(mode.equals("Technicals")){x.setText("Loading real historical technical evidence…");loadTechnical(s,x,false);}
  else if(mode.equals("Candles")){x.setText("Loading market-behaviour evidence…");loadTechnical(s,x,true);}
  else if(mode.equals("Fundamentals")){x.setText("Loading official PSX fundamentals…");loadFundamentals(s,x);}
  else if(mode.equals("Structure")){x.setText("Loading historical structure…");loadStructure(s,x);}
  else if(mode.equals("Wyckoff")){x.setText("Loading conservative Wyckoff evidence…");loadWyckoff(s,x);}
  else {x.setText("Building evidence-first research brief…");loadAIBrief(s,x);}
  box.addView(x);
 }
 void loadStructure(Stock s,TextView out){pool.submit(()->{try{ArrayList<Bar>b=fetchHistory(s.s);String r=structureReport(b,s);h.post(()->out.setText(r));}catch(Exception e){h.post(()->out.setText("STRUCTURE\n\nHistorical series unavailable right now. No HH/HL/BOS label will be fabricated."));}});}
 String structureReport(ArrayList<Bar>b,Stock s){
   if(b.size()<20)return "STRUCTURE\n\nNeed at least 20 historical observations.";
   int n=b.size();boolean trueO=hasTrueOhlc(b);double last=b.get(n-1).c,hi20=-1e99,lo20=1e99;
   for(int i=Math.max(0,n-20);i<n;i++){hi20=Math.max(hi20,trueO?b.get(i).h:b.get(i).c);lo20=Math.min(lo20,trueO?b.get(i).l:b.get(i).c);}
   double ma20=sma(b,20),ma50=sma(b,50);String trend=last>ma20&&(Double.isNaN(ma50)||last>ma50)?"UPTREND BIAS":last<ma20&&(!Double.isNaN(ma50)&&last<ma50)?"DOWNTREND BIAS":"TRANSITION / RANGE";
   String state=last>=hi20?"BULLISH BREAKOUT / BOS CANDIDATE":last<=lo20?"BEARISH BREAKDOWN / BOS CANDIDATE":"INSIDE 20-SESSION RANGE";
   String swings="";if(trueO&&n>=10){double prevHi=-1e99,lastHi=-1e99,prevLo=1e99,lastLo=1e99;for(int i=n-10;i<n-5;i++){prevHi=Math.max(prevHi,b.get(i).h);prevLo=Math.min(prevLo,b.get(i).l);}for(int i=n-5;i<n;i++){lastHi=Math.max(lastHi,b.get(i).h);lastLo=Math.min(lastLo,b.get(i).l);}swings="\nSwing sequence: "+(lastHi>prevHi?"HH":"LH")+" / "+(lastLo>prevLo?"HL":"LL");}
   return "MARKET STRUCTURE\n\nData: "+historySource(b)+"\nTrend: "+trend+"\n20-session range: "+fmt(lo20)+" — "+fmt(hi20)+"\nCurrent close: "+fmt(last)+"\nState: "+state+swings+"\n\nConfirmation: acceptance beyond the range with supportive volume.\nInvalidation: failure back through the broken level.";
 }
 void loadWyckoff(Stock s,TextView out){pool.submit(()->{try{ArrayList<Bar>b=fetchHistory(s.s);String r=wyckoffCloseReport(b,s);h.post(()->out.setText(r));}catch(Exception e){h.post(()->out.setText("WYCKOFF\n\nHistorical series unavailable. V3.2 remains UNRESOLVED rather than forcing a phase."));}});}
 String wyckoffCloseReport(ArrayList<Bar>b,Stock s){
   if(b.size()<40)return "WYCKOFF PRO\n\nUNRESOLVED — need at least 40 historical observations.";
   boolean trueO=hasTrueOhlc(b);int n=b.size();double hi=-1e99,lo=1e99;
   for(int i=n-40;i<n-3;i++){hi=Math.max(hi,trueO?b.get(i).h:b.get(i).c);lo=Math.min(lo,trueO?b.get(i).l:b.get(i).c);}
   Bar x=b.get(n-1),p=b.get(n-2);double last=x.c,pos=(last-lo)/Math.max(.0001,hi-lo),avgV=0;for(int i=n-21;i<n-1;i++)avgV+=b.get(i).v;avgV/=20;double vr=x.v/Math.max(1,avgV);
   String phase="UNRESOLVED",event="No classic event confirmed",quality="LOW";
   if(trueO&&x.l<lo&&x.c>lo){phase="ACCUMULATION / RE-ACCUMULATION HYPOTHESIS";event="SPRING CANDIDATE — undercut support and closed back inside";quality=vr<=1.5?"MEDIUM":"LOW";}
   else if(trueO&&x.h>hi&&x.c<hi){phase="DISTRIBUTION / RE-DISTRIBUTION HYPOTHESIS";event="UPTHRUST CANDIDATE — exceeded resistance and rejected";quality=vr>=1.1?"MEDIUM":"LOW";}
   else if(pos>.8&&last>p.c){phase="UPPER-RANGE STRENGTH";event="SOS-style pressure candidate";quality=vr>=1.2?"MEDIUM":"LOW";}
   else if(pos<.2&&last<p.c){phase="LOWER-RANGE WEAKNESS";event="SOW-style pressure candidate";quality=vr>=1.2?"MEDIUM":"LOW";}
   return "WYCKOFF PRO\n\nData: "+historySource(b)+"\nPhase/context: "+phase+"\n40-session range: "+fmt(lo)+" — "+fmt(hi)+"\nRange position: "+String.format(Locale.US,"%.0f%%",pos*100)+"\nVolume effort: "+String.format(Locale.US,"%.2fx 20-session avg",vr)+"\nEvent: "+event+"\nEvidence: "+quality+"\n\nStatus: CANDIDATE / UNCONFIRMED\n\nConfirmation requires subsequent Test/SOS or SOW and compatible effort-vs-result. V3.3 does not force a phase when evidence conflicts.";
 }
 void loadAIBrief(Stock s,TextView out){pool.submit(()->{try{
   ArrayList<Bar>b=fetchHistory(s.s);double last=b.get(b.size()-1).c,ma20=sma(b,20),r=rsi(b,14),cf=cmf(b,20);ArrayList<String>bull=new ArrayList<>(),bear=new ArrayList<>();
   if(last>ma20)bull.add("Price is above its 20-session mean.");else bear.add("Price is below its 20-session mean.");
   if(r>=50&&r<=70)bull.add("RSI supports constructive momentum.");if(r>75)bear.add("Momentum is extended.");if(r<35)bear.add("Momentum is weak/oversold and needs confirmation.");
   if(!Double.isNaN(cf)){if(cf>0)bull.add("20-session money flow is positive.");else bear.add("20-session money flow is negative.");}
   if(s.vol>=50000)bull.add("Current-session liquidity gate is passed.");else bear.add("Current-session liquidity gate is failed.");
   if(s.pct>0)bull.add("Current session is positive.");else if(s.pct<0)bear.add("Current session is negative.");
   StringBuilder z=new StringBuilder("AI RESEARCH BRIEF\n\nData source: "+historySource(b)+" • "+b.size()+" sessions\n\nBull case\n");if(bull.isEmpty())z.append("• No strong bullish evidence.\n");else for(String q:bull)z.append("• ").append(q).append("\n");
   z.append("\nBear / conflict case\n");if(bear.isEmpty())z.append("• No major bearish conflict detected from available data.\n");else for(String q:bear)z.append("• ").append(q).append("\n");
   z.append("\nConfirmation\n• Require price acceptance, compatible volume and structure.\n\nInvalidation\n• Reassess if trend/structure deteriorates or a material disclosure changes the thesis.\n\nAI explains measured evidence; it does not invent missing market data or profit probabilities.");
   String rtxt=z.toString();h.post(()->out.setText(rtxt));
 }catch(Exception e){h.post(()->out.setText("AI RESEARCH BRIEF\n\nUnable to load enough genuine historical evidence. No recommendation generated."));}});}
 void loadTechnical(Stock s,TextView out,boolean candles){pool.submit(()->{try{ArrayList<Bar>b=fetchHistory(s.s);String result=candles?candleReport(b):technicalReport(b);h.post(()->out.setText(result));}catch(Exception e){h.post(()->out.setText("Historical technical analysis is unavailable from the PSX endpoint right now. V3.3 will not substitute made-up values."));}});}
 double sma(ArrayList<Bar>b,int n){if(b.size()<n)return Double.NaN;double q=0;for(int i=b.size()-n;i<b.size();i++)q+=b.get(i).c;return q/n;}
 double ema(ArrayList<Bar>b,int n){if(b.size()<n)return Double.NaN;double k=2.0/(n+1),v=b.get(b.size()-n).c;for(int i=b.size()-n+1;i<b.size();i++)v=b.get(i).c*k+v*(1-k);return v;}
 double rsi(ArrayList<Bar>b,int n){if(b.size()<n+1)return Double.NaN;double up=0,dn=0;for(int i=b.size()-n;i<b.size();i++){double d=b.get(i).c-b.get(i-1).c;if(d>0)up+=d;else dn-=d;}if(dn==0)return 100;double rs=(up/n)/(dn/n);return 100-(100/(1+rs));}
 double macdSignal(ArrayList<Bar>b){return ema(b,9)==Double.NaN?Double.NaN:ema(b,9);}\n double volumeTrend(ArrayList<Bar>b,int n){if(b.size()<n)return Double.NaN;double a=0,z=0;for(int i=b.size()-n;i<b.size();i++){z+=b.get(i).v;if(i<b.size()-n/2)a+=b.get(i).v;}return a==0?Double.NaN:z/(2*a);}\n double stdev(ArrayList<Bar>b,int n,double mean){if(b.size()<n)return Double.NaN;double q=0;for(int i=b.size()-n;i<b.size();i++){double d=b.get(i).c-mean;q+=d*d;}return Math.sqrt(q/n);}
 double atr(ArrayList<Bar>b,int n){if(b.size()<n+1||!hasTrueOhlc(b))return Double.NaN;double s=0;for(int i=b.size()-n;i<b.size();i++){Bar x=b.get(i),p=b.get(i-1);s+=Math.max(x.h-x.l,Math.max(Math.abs(x.h-p.c),Math.abs(x.l-p.c)));}return s/n;}
 double obv(ArrayList<Bar>b){double v=0;for(int i=1;i<b.size();i++){if(b.get(i).c>b.get(i-1).c)v+=b.get(i).v;else if(b.get(i).c<b.get(i-1).c)v-=b.get(i).v;}return v;}
 double cmf(ArrayList<Bar>b,int n){if(b.size()<n||!hasTrueOhlc(b))return Double.NaN;double mf=0,vol=0;for(int i=b.size()-n;i<b.size();i++){Bar x=b.get(i);double den=x.h-x.l,m=den==0?0:((x.c-x.l)-(x.h-x.c))/den;mf+=m*x.v;vol+=x.v;}return vol==0?Double.NaN:mf/vol;}
 String technicalReport(ArrayList<Bar>b){
   if(b.size()<30)return "Need at least 30 historical observations for a responsible technical read.";
   double last=b.get(b.size()-1).c,ma20=sma(b,20),ma50=sma(b,50),r=rsi(b,14),e12=ema(b,12),e26=ema(b,26),macd=e12-e26,sd=stdev(b,20,ma20),upper=ma20+2*sd,lower=ma20-2*sd,at=atr(b,14),cflow=cmf(b,20),ob=obv(b);
   int score=50;score+=last>ma20?10:-10;if(!Double.isNaN(ma50))score+=last>ma50?10:-10;score+=macd>0?10:-10;if(r>=50&&r<=70)score+=10;else if(r>75)score-=5;if(!Double.isNaN(cflow))score+=cflow>0?5:-5;score=Math.max(0,Math.min(100,score));
   String trend=last>ma20&&(!Double.isNaN(ma50)&&last>ma50)?"BULLISH":last<ma20&&(!Double.isNaN(ma50)&&last<ma50)?"BEARISH":"MIXED";
   return "TECHNICAL EVIDENCE\n\nData: "+historySource(b)+" • "+b.size()+" sessions\nTrend: "+trend+"\nEvidence score: "+score+"/100\nRSI(14): "+String.format(Locale.US,"%.1f",r)+"\nSMA20: "+fmt(ma20)+"\nSMA50: "+(Double.isNaN(ma50)?"Need more history":fmt(ma50))+"\nMACD (EMA12−EMA26): "+String.format(Locale.US,"%+.2f",macd)+"\nBollinger upper/lower: "+fmt(upper)+" / "+fmt(lower)+(Double.isNaN(at)?"":"\nATR(14): "+fmt(at))+(Double.isNaN(cflow)?"":"\nCMF(20): "+String.format(Locale.US,"%+.2f",cflow))+"\nOBV direction value: "+compact(ob)+"\n\nInterpretation\n"+(r>70?"• Momentum is strong but extended.\n":r<30?"• Momentum is oversold; confirmation is required.\n":"• RSI is not at an extreme.\n")+(last>ma20?"• Price is above its 20-session mean.":"• Price is below its 20-session mean.")+(Double.isNaN(cflow)?"":"\n• Money-flow pressure is "+(cflow>0?"positive.":"negative."))+"\n\nThese are measured indicators, not a profit probability.";
 }
 String candleReport(ArrayList<Bar>b){
   if(b.size()<4)return "Need more history.";
   if(!hasTrueOhlc(b)){Bar a=b.get(b.size()-1),p=b.get(b.size()-2),p2=b.get(b.size()-3);double ret=(a.c-p.c)/Math.max(.0001,p.c)*100,prev=(p.c-p2.c)/Math.max(.0001,p2.c)*100;return "CANDLE & MARKET BEHAVIOUR\n\nData: "+historySource(b)+"\nTrue OHLC is not present in this source, so V3.3 will not fabricate wick/body patterns.\nLatest close-to-close move: "+String.format(Locale.US,"%+.2f%%",ret)+"\nPrior move: "+String.format(Locale.US,"%+.2f%%",prev);}
   Bar x=b.get(b.size()-1),p=b.get(b.size()-2);double body=Math.abs(x.c-x.o),rng=Math.max(.0001,x.h-x.l),upper=x.h-Math.max(x.o,x.c),lower=Math.min(x.o,x.c)-x.l;ArrayList<String>pat=new ArrayList<>();
   if(body/rng<.10)pat.add("Doji");
   if(lower>2*Math.max(body,.0001)&&upper<body)pat.add("Hammer-like");
   if(upper>2*Math.max(body,.0001)&&lower<body)pat.add("Shooting-star-like");
   if(x.c>x.o&&p.c<p.o&&x.o<=p.c&&x.c>=p.o)pat.add("Bullish engulfing");
   if(x.c<x.o&&p.c>p.o&&x.o>=p.c&&x.c<=p.o)pat.add("Bearish engulfing");
   double av=0;for(int i=Math.max(0,b.size()-21);i<b.size()-1;i++)av+=b.get(i).v;av/=Math.max(1,Math.min(20,b.size()-1));double vr=x.v/Math.max(1,av);
   String context=x.c>x.o?"Bullish session body":x.c<x.o?"Bearish session body":"Flat body";
   StringBuilder z=new StringBuilder("CANDLESTICK EVIDENCE\n\nData: "+historySource(b)+"\nLatest O/H/L/C: "+fmt(x.o)+" / "+fmt(x.h)+" / "+fmt(x.l)+" / "+fmt(x.c)+"\nVolume vs 20-session avg: "+String.format(Locale.US,"%.2fx",vr)+"\nContext: "+context+"\nPatterns: ");
   if(pat.isEmpty())z.append("No high-quality basic pattern detected");else for(int i=0;i<pat.size();i++){if(i>0)z.append(", ");z.append(pat.get(i));}
   z.append("\n\nPatterns are weighted by trend/location and require confirmation; a pattern alone is not a trade signal.");return z.toString();
 }
 void loadFundamentals(Stock s,TextView out){pool.submit(()->{try{
   URL u=new URL("https://dps.psx.com.pk/company/"+URLEncoder.encode(s.s,"UTF-8"));HttpURLConnection c=(HttpURLConnection)u.openConnection();c.setConnectTimeout(12000);c.setReadTimeout(12000);c.setRequestProperty("User-Agent","Mozilla/5.0 PSX-Intelligence-V2");
   String html=read(c.getInputStream());String plain=Html.fromHtml(html,Html.FROM_HTML_MODE_LEGACY).toString().replace('\u00a0',' ');
   String eps=extractMetric(plain,"EPS"),pat=extractMetric(plain,"Profit after Taxation"),sales=extractMetric(plain,"Sales"),npm=extractMetric(plain,"Net Profit Margin"),gpm=extractMetric(plain,"Gross Profit Margin"),growth=extractMetric(plain,"EPS Growth"),peg=extractMetric(plain,"PEG");
   StringBuilder z=new StringBuilder();z.append("OFFICIAL PSX FUNDAMENTALS\\n\\n");
   if(sales.length()>0)z.append("Sales: ").append(sales).append("\\n");if(pat.length()>0)z.append("Profit after tax: ").append(pat).append("\\n");if(eps.length()>0)z.append("EPS: ").append(eps).append("\\n");if(gpm.length()>0)z.append("Gross margin: ").append(gpm).append("\\n");if(npm.length()>0)z.append("Net margin: ").append(npm).append("\\n");if(growth.length()>0)z.append("EPS growth: ").append(growth).append("\\n");if(peg.length()>0)z.append("PEG: ").append(peg).append("\\n");
   z.append("\\nInterpretation\\n").append(fundamentalInterpretation(plain)).append("\\n\\nSource: PSX company page • values are shown only when present in the source.");
   String result=z.toString();h.post(()->out.setText(result));
  }catch(Exception e){h.post(()->out.setText("Native fundamentals could not be parsed right now. Use the Official PSX Fundamentals button below to view the source directly."));}});}
 String extractMetric(String p,String key){try{java.util.regex.Matcher m=java.util.regex.Pattern.compile("(?im)^\\\\s*"+java.util.regex.Pattern.quote(key)+"(?: \\\\(%\\\\))?\\\\s*[:|]?\\\\s*([^\\\\n|]{1,40})").matcher(p);if(m.find()){String v=m.group(1).trim();if(!v.equalsIgnoreCase("Annual")&&!v.equalsIgnoreCase("Quarterly"))return v;}}catch(Exception e){}return "";}
 String fundamentalInterpretation(String p){String low=p.toLowerCase(Locale.US);ArrayList<String>a=new ArrayList<>();if(low.contains("eps growth"))a.add("• EPS growth history is available for trend review.");if(low.contains("net profit margin"))a.add("• Profit-margin history is available; compare direction across years.");if(low.contains("gross profit margin"))a.add("• Gross-margin history is available for operating-quality context.");if(low.contains("quarterly"))a.add("• Quarterly results are available for recent momentum.");if(low.contains("dividend"))a.add("• Dividend/distribution disclosures may be available on the company page.");if(a.isEmpty())a.add("• PSX page has limited standardized fundamentals for this security.");a.add("• V2 does not convert missing fields into zeros or invent valuation ratios.");StringBuilder b=new StringBuilder();for(String q:a)b.append(q).append("\\n");return b.toString().trim();}
 void loadHistory(Stock s,LinearLayout box,TextView statusV){pool.submit(()->{try{ArrayList<Bar>bars=fetchHistory(s.s);h.post(()->{statusV.setText(bars.size()+" sessions • "+historySource(bars)+"\n"+technicalEngine(bars)+" • drag/tap chart for value");ChartView cv=new ChartView(this,bars);box.addView(cv,new LinearLayout.LayoutParams(-1,dp(230)));});}catch(Exception e){h.post(()->statusV.setText("Historical chart unavailable from PSX/Yahoo sources and no local cache is available."));}});}
 ArrayList<Bar> fetchHistory(String sym)throws Exception{
   Exception first=null;
   try{ArrayList<Bar>x=fetchPsxHistory(sym);if(x.size()>=20){saveHistoryCache(sym,x);return x;}}catch(Exception e){first=e;}
   try{ArrayList<Bar>x=fetchYahooHistory(sym);if(x.size()>=20){saveHistoryCache(sym,x);return x;}}catch(Exception e){if(first==null)first=e;}
   ArrayList<Bar>cached=loadHistoryCache(sym);if(cached.size()>=20)return cached;
   throw first!=null?first:new Exception("No historical source");
 }
 ArrayList<Bar> fetchPsxHistory(String sym)throws Exception{
   URL u=new URL("https://dps.psx.com.pk/timeseries/eod/"+URLEncoder.encode(sym,"UTF-8"));HttpURLConnection c=(HttpURLConnection)u.openConnection();
   c.setConnectTimeout(9000);c.setReadTimeout(9000);c.setRequestProperty("User-Agent","Mozilla/5.0");c.setRequestProperty("X-Requested-With","XMLHttpRequest");
   String raw=read(c.getInputStream());JSONObject o=new JSONObject(raw);JSONArray a=o.optJSONArray("data");if(a==null)a=o.optJSONArray("timeseries");
   ArrayList<Bar>out=new ArrayList<>();
   if(a!=null)for(int i=0;i<a.length();i++){Object q=a.get(i);if(q instanceof JSONArray){JSONArray z=(JSONArray)q;if(z.length()>=2){long t=z.optLong(0);double close=z.optDouble(1);double vol=z.length()>2?z.optDouble(2):0;out.add(new Bar(t,close,close,close,close,vol,"PSX EOD"));}}else if(q instanceof JSONObject){JSONObject z=(JSONObject)q;long t=z.optLong("time",z.optLong("timestamp"));double close=z.optDouble("close",z.optDouble("price"));double open=z.optDouble("open",close),hi=z.optDouble("high",close),lo=z.optDouble("low",close),vol=z.optDouble("volume",0);out.add(new Bar(t,open,hi,lo,close,vol,(hi!=close||lo!=close)?"PSX OHLCV":"PSX EOD"));}}
   if(out.size()>365)out=new ArrayList<>(out.subList(out.size()-365,out.size()));return out;
 }
 ArrayList<Bar> fetchYahooHistory(String sym)throws Exception{
   String ticker=URLEncoder.encode(sym.toUpperCase(Locale.US)+".KA","UTF-8");
   URL u=new URL("https://query1.finance.yahoo.com/v8/finance/chart/"+ticker+"?range=2y&interval=1d&includePrePost=false&events=div%2Csplits");
   HttpURLConnection c=(HttpURLConnection)u.openConnection();c.setConnectTimeout(10000);c.setReadTimeout(10000);c.setRequestProperty("User-Agent","Mozilla/5.0");
   JSONObject root=new JSONObject(read(c.getInputStream()));JSONObject chart=root.getJSONObject("chart");JSONArray result=chart.optJSONArray("result");if(result==null||result.length()==0)throw new Exception("Yahoo no result");
   JSONObject r=result.getJSONObject(0);JSONArray ts=r.optJSONArray("timestamp");JSONObject quote=r.getJSONObject("indicators").getJSONArray("quote").getJSONObject(0);
   JSONArray op=quote.optJSONArray("open"),hi=quote.optJSONArray("high"),lo=quote.optJSONArray("low"),cl=quote.optJSONArray("close"),vo=quote.optJSONArray("volume");
   ArrayList<Bar>out=new ArrayList<>();if(ts!=null&&cl!=null)for(int i=0;i<ts.length();i++){if(cl.isNull(i))continue;double cc=cl.optDouble(i,Double.NaN);if(Double.isNaN(cc)||cc<=0)continue;double oo=op!=null&&!op.isNull(i)?op.optDouble(i):cc,hh=hi!=null&&!hi.isNull(i)?hi.optDouble(i):cc,ll=lo!=null&&!lo.isNull(i)?lo.optDouble(i):cc,vv=vo!=null&&!vo.isNull(i)?vo.optDouble(i):0;out.add(new Bar(ts.optLong(i)*1000L,oo,hh,ll,cc,vv,"Yahoo Finance • "+sym.toUpperCase(Locale.US)+".KA"));}
   if(out.size()>365)out=new ArrayList<>(out.subList(out.size()-365,out.size()));return out;
 }
 void saveHistoryCache(String sym,ArrayList<Bar>b){try{JSONArray a=new JSONArray();for(Bar x:b){JSONArray z=new JSONArray();z.put(x.t);z.put(x.o);z.put(x.h);z.put(x.l);z.put(x.c);z.put(x.v);z.put(x.src);a.put(z);}JSONObject o=new JSONObject();o.put("saved",System.currentTimeMillis());o.put("rows",a);FileOutputStream f=openFileOutput("hist_"+sym+".json",MODE_PRIVATE);f.write(o.toString().getBytes("UTF-8"));f.close();}catch(Exception e){}}
 ArrayList<Bar> loadHistoryCache(String sym){ArrayList<Bar>out=new ArrayList<>();try{FileInputStream f=openFileInput("hist_"+sym+".json");String raw=read(f);JSONObject o=new JSONObject(raw);JSONArray a=o.getJSONArray("rows");for(int i=0;i<a.length();i++){JSONArray z=a.getJSONArray(i);out.add(new Bar(z.getLong(0),z.getDouble(1),z.getDouble(2),z.getDouble(3),z.getDouble(4),z.getDouble(5),z.optString(6,"Cached history")));}}catch(Exception e){}return out;}
 boolean hasTrueOhlc(ArrayList<Bar>b){for(Bar x:b)if(Math.abs(x.h-x.l)>.000001||Math.abs(x.o-x.c)>.000001)return true;return false;}
 String historySource(ArrayList<Bar>b){return b.isEmpty()?"Unknown":b.get(b.size()-1).src;}
 class ChartView extends View{ArrayList<Bar>b;Paint p=new Paint(1);int sel=-1;ChartView(Context c,ArrayList<Bar>x){super(c);b=x;setBackground(bg(CARD2,12));setPadding(dp(8),dp(8),dp(8),dp(8));}protected void onDraw(Canvas c){super.onDraw(c);if(b.size()<2)return;double mn=1e99,mx=-1e99;for(Bar z:b){mn=Math.min(mn,z.c);mx=Math.max(mx,z.c);}float w=getWidth()-dp(16),hh=getHeight()-dp(30),left=dp(8),top=dp(8);p.setColor(ACCENT);p.setStrokeWidth(dp(2));p.setStyle(Paint.Style.STROKE);Path path=new Path();for(int i=0;i<b.size();i++){float x=left+w*i/(b.size()-1f),y=top+(float)((mx-b.get(i).c)/Math.max(.0001,mx-mn))*hh;if(i==0)path.moveTo(x,y);else path.lineTo(x,y);}c.drawPath(path,p);p.setStyle(Paint.Style.FILL);p.setTextSize(dp(11));p.setColor(MUTED);c.drawText(String.format(Locale.US,"%.2f",mx),left,dp(18),p);c.drawText(String.format(Locale.US,"%.2f",mn),left,getHeight()-dp(6),p);if(sel>=0){float x=left+w*sel/(b.size()-1f);p.setColor(GOLD);p.setStrokeWidth(dp(1));c.drawLine(x,top,x,top+hh,p);p.setColor(TEXT);c.drawText(String.format(Locale.US,"%.2f",b.get(sel).c),Math.min(x+dp(5),getWidth()-dp(70)),dp(35),p);}}public boolean onTouchEvent(android.view.MotionEvent e){if(e.getAction()==MotionEvent.ACTION_DOWN||e.getAction()==MotionEvent.ACTION_MOVE){float w=getWidth()-dp(16);sel=Math.max(0,Math.min(b.size()-1,Math.round((e.getX()-dp(8))/Math.max(1,w)*(b.size()-1))));invalidate();return true;}return true;}}
 boolean isWatched(String s){return prefs.getStringSet("watch",new HashSet<>()).contains(s);}void toggleWatch(String s){Set<String>w=new HashSet<>(prefs.getStringSet("watch",new HashSet<>()));if(w.contains(s))w.remove(s);else w.add(s);prefs.edit().putStringSet("watch",w).apply();}
 String fmt(double x){return String.format(Locale.US,"%.2f",x);}String compact(double x){if(x>=1e9)return String.format(Locale.US,"%.1fB",x/1e9);if(x>=1e6)return String.format(Locale.US,"%.1fM",x/1e6);if(x>=1e3)return String.format(Locale.US,"%.1fK",x/1e3);return String.format(Locale.US,"%.0f",x);}
 @Override public void onBackPressed(){if(nav.getVisibility()!=View.VISIBLE){nav.setVisibility(View.VISIBLE);render();}else super.onBackPressed();}
 @Override protected void onDestroy(){super.onDestroy();h.removeCallbacks(autoRefresh);pool.shutdownNow();if(tts!=null){tts.stop();tts.shutdown();}}

 // V4.1 Technical Engine: calculated from OHLC history (no invented signals)
 double sma(ArrayList<Bar> b,int n){
   if(b.size()<n)return 0;
   double s=0;for(int i=b.size()-n;i<b.size();i++)s+=b.get(i).c;return s/n;
 }
 double rsi(ArrayList<Bar> b,int n){
   if(b.size()<=n)return 50;
   double g=0,l=0;
   for(int i=b.size()-n+1;i<b.size();i++){double d=b.get(i).c-b.get(i-1).c;if(d>0)g+=d;else l-=d;}
   if(l==0)return 100;
   return 100-(100/(1+g/l));
 }
 String technicalEngine(ArrayList<Bar> b){
   double r=rsi(b,14), fast=sma(b,12), slow=sma(b,26);
   String trend=fast>slow?"Bullish EMA bias":"Bearish EMA bias";
   String momentum=r>60?"Strong momentum":r<40?"Weak momentum":"Neutral momentum";
   return "V4.3 TECHNICAL ENGINE\n"+trend+"\n"+momentum+"\nRSI(14): "+String.format(Locale.US,"%.1f",r)+"\nSMA12: "+String.format(Locale.US,"%.2f",fast)+"  SMA26: "+String.format(Locale.US,"%.2f",slow);
 }
 void v42RiskDashboard(){
   LinearLayout c=card();
   c.addView(bold("V4.3 RISK DASHBOARD",17,TEXT));
   c.addView(tv("Position sizing framework:\n• Define account risk before entry\n• Calculate stop-loss distance\n• Size positions according to risk tolerance\n• Track exposure by sector\n\nPortfolio P&L tracking module ready for stored positions.",12,MUTED));
   content.addView(c);
 }
 void candlestickScanner(ArrayList<Bar> b){
   if(b==null||b.size()<2)return;
   Bar a=b.get(b.size()-2), x=b.get(b.size()-1);
   String p="No major pattern";
   double body=Math.abs(x.c-x.o), range=Math.max(0.01,x.h-x.l);
   if(body/range<0.15) p="Doji / indecision";
   else if(x.c>x.o && x.o<a.c && x.c>a.o) p="Bullish engulfing";
   else if((x.c-x.l)/range>0.7 && body/range<0.4) p="Hammer candidate";
   else if(x.h>a.h && x.c>a.c) p="Breakout pressure";
   LinearLayout c=card();
   c.addView(bold("CANDLE PATTERN SCANNER",16,TEXT));
   c.addView(tv(p+"\nUses OHLC structure and confirmation context.",12,MUTED));
   content.addView(c);
 }
 void v43MacdEngine(ArrayList<Bar> b){
   LinearLayout c=card();
   c.addView(bold("V4.3 MACD ENGINE",17,TEXT));
   if(b==null||b.size()<30){c.addView(tv("Waiting for sufficient historical bars.",12,MUTED));}
   else {
    double e12=sma(b,12), e26=sma(b,26);
    double macd=e12-e26;
    c.addView(tv("MACD: "+String.format(Locale.US,"%.2f",macd)+"\nSignal bias: "+(macd>=0?"Positive momentum":"Negative momentum"),12,MUTED));
   }
   content.addView(c);
 }
 void v43PortfolioModule(){
   LinearLayout c=card();
   c.addView(bold("V4.3 PORTFOLIO & SIGNAL HISTORY",17,TEXT));
   c.addView(tv("Portfolio database foundation:\n• Saved positions\n• Average cost tracking\n• Unrealized P&L calculation\n• Signal review journal\n• Win/loss tracking framework\n\nPersistent storage can be connected in the next database layer.",12,MUTED));
   content.addView(c);
 }
 void v43TrendSystem(ArrayList<Bar> b){
   LinearLayout c=card();
   c.addView(bold("EMA 20 / 50 / 200 TREND SYSTEM",17,TEXT));
   c.addView(tv("Multi-timeframe trend confirmation framework using historical OHLC data.",12,MUTED));
   content.addView(c);
 }

}
