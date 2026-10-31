# PM_CSP27
CafeQuick: Cafeteria Pre-Order &amp; Pickup System
- اضفة كودات اولية عشان تكون نقطة بداية ولا اشي هون رسمي عدلو زي ما بدكم او حتى احذفو و ابدو من الصفر 
- عشان تنزلو البكجات المطلوبة   
`````
pip install fastapi uvicorn sqlmodel
```````
- عشان تعملو الداتا بيس اول مرة او ترجعو البيانات الاصلية
```
python Database/cafequick_db.py
```
- عشان تشغلو الباك ايند
```
uvicorn Backend.main:app --reload
```
- بعدها افتحو تيرمينل جيديد للفرنت ايند
```
cd Frontend
python3 -m http.server 5500
```
