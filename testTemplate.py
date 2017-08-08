from docxtpl import DocxTemplate
import json


with open('sample_causelist.json') as data_file:
    data = json.loads(data_file.read())
tpl=DocxTemplate('causelists.docx')
tpl.render(data)
tpl.save('causelists_result.docx')
