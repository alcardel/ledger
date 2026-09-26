import base64, csv, io, hashlib
from decimal import Decimal
from pathlib import Path
import fitz
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from .providers import extract_with_provider

class ExtractedItem(BaseModel):
    key: str
    value: str | float | int | None
    source_text: str
    period: str | None = None
class Extraction(BaseModel):
    fields: list[ExtractedItem] = Field(default_factory=list)

def inspect_file(content, name):
    suffix=Path(name).suffix.lower()
    if suffix not in ['.pdf','.png','.jpg','.jpeg','.csv']: raise ValueError('Use PDF, PNG, JPEG or CSV')
    if len(content)>25*1024*1024: raise ValueError('File exceeds 25 MB')
    if suffix=='.pdf':
        doc=fitz.open(stream=content,filetype='pdf')
        if doc.page_count>100: raise ValueError('Document exceeds 100 pages')
        return {'pages':doc.page_count,'locked':doc.needs_pass}
    if suffix!='.csv':
        Image.open(io.BytesIO(content)).verify()
    return {'pages':1,'locked':False}

def csv_transactions(content, mapping=None):
    mapping=mapping or {'date':'date','description':'description','credit':'credit','debit':'debit','balance':'balance'}
    reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    if not reader.fieldnames or not all(mapping.get(k,k) in reader.fieldnames for k in ['date','description','credit','debit']): raise ValueError('Map date, description, credit and debit CSV columns before processing')
    result=[]; seen=set()
    for i,row in enumerate(reader,2):
        if i>100002: raise ValueError('CSV exceeds 100,000 rows')
        def amount(k):
            raw=row.get(mapping.get(k,k),'')
            n=Decimal(raw.replace(',','') or '0')
            if not n.is_finite() or n<0: raise ValueError(f'Invalid {k} on row {i}')
            return str(n)
        tx={'date':row[mapping['date']],'description':row[mapping['description']],'credit':amount('credit'),'debit':amount('debit'),'balance':row.get(mapping.get('balance','balance')),'row':i,'category':'unclassified'}
        from datetime import date
        date.fromisoformat(tx['date'])
        fingerprint=hashlib.sha256(str((tx['date'],tx['description'],tx['credit'],tx['debit'])).encode()).hexdigest()
        tx['duplicate_candidate']=fingerprint in seen; seen.add(fingerprint); result.append(tx)
    return result

def extract(path, field_defs, password=None):
    content=Path(path).read_bytes(); suffix=Path(path).suffix.lower()
    if suffix=='.csv': return [],csv_transactions(content)
    pages=[]
    if suffix=='.pdf':
        doc=fitz.open(stream=content,filetype='pdf')
        if doc.needs_pass and not doc.authenticate(password or ''): raise ValueError('Password protected PDF. Unlock or upload an unlocked copy.')
        for i,page in enumerate(doc):
            text=page.get_text()
            img=None if len(text.strip())>80 else base64.b64encode(page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).tobytes('png')).decode()
            pages.append((i+1,text,img))
    else:
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert('RGB'); im.thumbnail((1600,2000))
        buf=io.BytesIO(); im.save(buf,format='PNG'); pages=[(1,'',base64.b64encode(buf.getvalue()).decode())]
    output=[]
    allowed={f['key']:f for f in field_defs}
    for number,text,img in pages:
        prompt='Extract matching fields from this page. Omit fields absent from the page. Use numeric strings without currency symbols, retain period and a verbatim source_text. Requested fields: '+str(field_defs)+'\nPAGE EVIDENCE:\n'+text[:24000]
        result=Extraction.model_validate(extract_with_provider(prompt,Extraction.model_json_schema(),[img] if img else None))
        for field in result.fields:
            if field.key not in allowed or field.value is None: continue
            if allowed[field.key].get('type','number')=='number':
                n=Decimal(str(field.value).replace(',',''))
                if not n.is_finite(): continue
                value=str(n)
            else: value=str(field.value)
            output.append({'key':field.key,'value':value,'source_text':field.source_text,'page':number,'period':field.period,'verified':False,'source_match':field.source_text in text if text else None})
    return output,[]
