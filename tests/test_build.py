import base64
import copy
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as E
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from update import build,workbook
from collection import collect,validate
N={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
snapshot=json.loads((ROOT/'docs/data.json').read_text())

class BuildChecks(unittest.TestCase):
    def test_exact_export_and_offline_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);build(snapshot,out)
            html=(out/'index.html').read_text()
            self.assertEqual(base64.b64decode(re.search(r'<script id="xlsx-data"[^>]*>(.*?)</script>',html)[1]),(out/'product-pulse.xlsx').read_bytes())
            self.assertEqual(json.loads(re.search(r'<script id="snapshot-data"[^>]*>(.*?)</script>',html,re.S)[1]),snapshot)
            with ZipFile(out/'product-pulse.xlsx') as z:
                self.assertIsNone(z.testzip())
                sheet=E.fromstring(z.read('xl/worksheets/sheet1.xml'))
                cells={c.get('r'):c for c in sheet.findall('.//m:c',N)}
                self.assertEqual(len(sheet.findall('.//m:sheetData/m:row',N)),len(snapshot['records'])+1)
                def value(c):return c.find('m:v',N).text if c.find('m:v',N) is not None else ''.join(c.itertext())
                for i,r in enumerate(snapshot['records'],2):
                    self.assertEqual(value(cells[f'A{i}']),r['title'])
                    self.assertEqual(value(cells[f'I{i}']),r['source_url'])
                    if r['metric_value'] is not None:self.assertEqual(float(value(cells[f'D{i}'])),r['metric_value'])
                    else:self.assertIsNone(cells[f'D{i}'].find('m:v',N))
                styles=E.fromstring(z.read('xl/styles.xml')).find('m:cellXfs',N)
                self.assertEqual(styles[int(cells['D2'].get('s'))].find('m:alignment',N).get('horizontal'),'center')
                self.assertEqual(value(cells['K1']),'Опубликовано (UTC)')
                self.assertEqual(value(cells['N1']),'Получено (UTC)')

    def test_source_failure_retains_dates(self):
        def fail():raise TimeoutError('offline failure check')
        module=types.SimpleNamespace(ROWS=[],STATUS=[],radar=fail,habr=fail,hn=fail)
        rows,status=collect(snapshot,module)
        self.assertEqual(sorted(rows,key=lambda r:r['source_url']),sorted(snapshot['records'],key=lambda r:r['source_url']))
        self.assertTrue(all(s['result']=='cached' for s in status))

    def test_variable_count_and_invalid_data(self):
        reduced=copy.deepcopy(snapshot);reduced['records']=snapshot['records'][:3]
        with ZipFile(BytesIO(workbook(reduced))) as z:
            table=E.fromstring(z.read('xl/tables/table1.xml'))
            self.assertEqual(table.get('ref'),'A1:N4')
        rows=copy.deepcopy(snapshot['records'][:3]);rows[0]['metric_value']=-1
        with self.assertRaises(ValueError):validate(rows,'Product Radar')

if __name__=='__main__':unittest.main()
