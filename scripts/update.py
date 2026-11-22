"""Portable scheduled build. Updates an Artifact Tool-authored XLSX template.

No private Codex runtime or external packages are required on GitHub Actions.
"""
import base64
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED

import collector
from collection import collect

ROOT=Path(__file__).resolve().parent.parent
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
E.register_namespace('',NS)
SITE='https://VidosIQ.github.io/PM-pulse-radar/'
def q(name):return '{'+NS+'}'+name
def date(value):
    if not value:return None
    dt=datetime.fromisoformat(value)
    if dt.tzinfo:dt=dt.astimezone(timezone.utc).replace(tzinfo=None)
    return (dt-datetime(1899,12,30)).total_seconds()/86400
def col(i):
    result=''
    while i:i,n=divmod(i-1,26);result=chr(65+n)+result
    return result

def workbook(snapshot):
    records=snapshot['records']; counts=Counter(r['source'] for r in records)
    data=[['Название','Источник','Тип записи','Показатель','Единица','Комментарии','Категории','Описание','Первоисточник','Сайт продукта','Опубликовано (UTC)','Начало периода','Конец периода','Получено (UTC)']]
    for r in records:
        period=r['period'].split('/') if r.get('period') else [None,None]
        data.append([r['title'],r['source'],{'article':'Статья','product_listing':'Карточка продукта','project_post':'Публикация о проекте'}[r['record_type']],r['metric_value'],'Голоса Radar' if r['source']=='Product Radar' else 'Баллы HN' if r['source']=='Show HN' else 'Не собирался',r.get('comments_count'),'; '.join(r['categories']),r.get('description'),r['source_url'],r.get('product_url'),date(r.get('published_at')),date(period[0]),date(period[1]),date(r['fetched_at'])])
    summary=[['Пульс продуктов — данные графиков',None],['Последняя попытка (UTC)',date(snapshot['completed_at'])],['Экспортируется весь срез; поиск и фильтры не применяются.',None],['Пустое значение означает отсутствие данных, не ноль.',None],['Состав выборки','Записей']]
    summary.extend([[s,counts[s]] for s in ('Product Radar','Show HN','Habr / Product Radar')]);summary.extend([['Всего',len(records)],['Доли записей не являются долями рынка; голоса и баллы не суммируются.',None]])
    for source,unit in [('Product Radar','Голоса'),('Show HN','Баллы HN')]:
        summary.append([source+': пять лидеров',unit])
        summary.extend([[r['title'],r['metric_value']] for r in sorted([r for r in records if r['source']==source],key=lambda r:-r['metric_value'])[:5]])
    topics=Counter(c for r in records if r['source']=='Product Radar' for c in set(r['categories']) if not re.match(r'^[🤝🔥🌐💰🎓💼👥👨]',c))
    # Use the exact browser-selected topic labels (Russian locale order) written
    # by the checked-in current sample; normal runs resolve ties with this key.
    # A locale-aware sort is supplied by ICU on the runner via the system locale.
    import locale
    try:locale.setlocale(locale.LC_COLLATE,'ru_RU.UTF-8')
    except locale.Error:pass
    summary.append(['Темы Product Radar','Карточек'])
    summary.extend([[name,num] for name,num in sorted(topics.items(),key=lambda x:(-x[1],locale.strxfrm(x[0])))[:4]])
    summary.append(['У карточки может быть несколько тем; служебные метки исключены.',None])
    about=[['О выборке','Пульс продуктов'],['Сайт дашборда',SITE],['Назначение','Учебный обзор продуктов, активности сообществ и кейсов. Это ограниченная выборка, не весь рынок.'],['Последняя попытка',snapshot['completed_at']+' (UTC). Запуск запланирован ежедневно в 09:15 МСК; возможна задержка GitHub Actions.'],['Что собрано',f"{len(records)} записей: до 10 карточек первого видимого набора Radar, первые 10 ID Show HN без удалённых, до 5 статей RSS компании Product Radar на Хабре."],['Шкала Product Radar','До пяти лидеров среди полученных карточек по data-votes. Голоса площадки не подтверждают продажи или спрос.'],['Шкала Show HN','До пяти лидеров среди полученных публикаций по score официального HN API. Выдача не строго хронологическая. Баллы не суммируются с голосами Radar.'],['Круговая диаграмма','Доли собранных записей по источникам, не доли рынка.'],['Темы Product Radar','Четыре наиболее частые категории полученных карточек; у карточки может быть несколько тем. Служебные метки исключены.'],['Свежие кейсы','До трёх последних по дате публикации статей из полученного RSS Хабра. Статья не равна отдельному продукту.'],['Даты и пропуски','Дата публикации и период выдачи не являются датой выхода продукта на рынок. Даты в таблице — UTC. Пустые числа не заменяются нулём. История роста не достраивается.'],['Выгрузка',f"Все {len(records)} записей независимо от поиска и фильтров. При ошибке источника используются прежние данные с прежней датой и статусом cached."],['Product Radar','https://productradar.ru/'],['HN API','https://github.com/HackerNews/API'],['Хабр RSS','https://habr.com/ru/rss/companies/productradar/articles/?fl=ru'],['Статус источников','Результат последней попытки и фактическое время получения']]
    for s in snapshot['sources']:about.append([s['source'],f"{s['result']}; записей: {s['records']}; получено: {s.get('data_fetched_at')}; {s.get('error','')}"])
    from io import BytesIO
    buf=BytesIO()
    with ZipFile(ROOT/'templates/export.xlsx') as original, ZipFile(buf,'w',ZIP_DEFLATED) as output:
        for name in original.namelist():
            content=original.read(name)
            for number,values in enumerate([data,summary,about],1):
                if name==f'xl/worksheets/sheet{number}.xml':
                    root=E.fromstring(content);sheet=root.find(q('sheetData'));old=list(sheet);sheet.clear()
                    for rownum,vals in enumerate(values,1):
                        sample=old[min(rownum-1,len(old)-1)]
                        row=E.SubElement(sheet,q('row'),dict(sample.attrib,r=str(rownum)))
                        styles={re.sub(r'\d','',c.get('r')):c.get('s','0') for c in sample}
                        if number==1 and rownum>1:
                            styles={re.sub(r'\d','',c.get('r')):c.get('s','0') for c in old[1]}
                        for i,v in enumerate(vals,1):
                            c=E.SubElement(row,q('c'),{'r':col(i)+str(rownum),'s':styles.get(col(i),'0')})
                            if v is None:continue
                            if type(v) in (int,float):E.SubElement(c,q('v')).text=str(v)
                            else:
                                c.set('t','inlineStr');text=E.SubElement(E.SubElement(c,q('is')),q('t'));text.text=str(v)
                        if number==2 and rownum>4:
                            isheader=vals[0] in ('Состав выборки','Product Radar: пять лидеров','Show HN: пять лидеров','Темы Product Radar')
                            ref=old[4] if isheader else old[5]
                            for cell,oldcell in zip(row,ref):cell.set('s',oldcell.get('s','0'))
                    dim=root.find(q('dimension'))
                    if dim is not None:dim.set('ref',f'A1:{col(len(values[0]))}{len(values)}')
                    content=E.tostring(root,encoding='utf-8',xml_declaration=True)
            if name.startswith('xl/tables/') and name.endswith('.xml'):
                root=E.fromstring(content);root.set('ref',f'A1:N{len(data)}')
                filt=root.find(q('autoFilter'))
                if filt is None:
                    filt=E.Element(q('autoFilter'));root.insert(0,filt)
                filt.set('ref',f'A1:N{len(data)}');content=E.tostring(root,encoding='utf-8',xml_declaration=True)
            output.writestr(name,content)
    return buf.getvalue()

def build(snapshot, target):
    target.mkdir(parents=True,exist_ok=True)
    xlsx=workbook(snapshot)
    html=(ROOT/'templates/index.html').read_text()
    html=re.sub(r'(<script id="snapshot-data"[^>]*>).*?(</script>)',lambda m:m[1]+json.dumps(snapshot,ensure_ascii=False).replace('<','\\u003c')+m[2],html,flags=re.S)
    payload=base64.b64encode(xlsx).decode()
    block='<script id="xlsx-data" type="application/octet-stream">'+payload+'</script><script>document.getElementById("export-excel").addEventListener("click",()=>{const raw=atob(document.getElementById("xlsx-data").textContent);const blob=new Blob([Uint8Array.from(raw,c=>c.charCodeAt(0))],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="product-pulse-'+snapshot['run_id']+'.xlsx";document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)});</script>'
    (target/'index.html').write_text(html.replace('</body>',block+'</body>'))
    (target/'product-pulse.xlsx').write_bytes(xlsx)
    (target/'data.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2))

def main():
    output=ROOT/'docs';previous=json.loads((output/'data.json').read_text())
    rows,status=collect(previous,collector)
    now=datetime.now(timezone.utc)
    snapshot=dict(previous,records=rows,sources=status,run_id=now.strftime('%Y%m%dT%H%M%SZ'),completed_at=now.isoformat(),parser_version='github-1.0')
    stage=ROOT/'.build';build(snapshot,stage)
    # All generation must succeed before touching committed data.
    for name in ('index.html','data.json','product-pulse.xlsx'):(output/name).write_bytes((stage/name).read_bytes())
    print('Built',len(rows),'records. Sources:',[(s['source'],s['result']) for s in status])

if __name__=='__main__':main()
