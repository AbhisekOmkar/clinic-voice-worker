# family_line_hi (PASS)

**agent** [en]: Hello! Apollo Clinic, Indiranagar and HSR Layout — this is Asha. How may I help you?

**user** [hi]: नमस्ते, अगले हफ़्ते डॉक्टर से अपॉइंटमेंट चाहिए।

**agent** [hi]: नमस्ते! किस डॉक्टर से मिलना है और कौन सा क्लिनिक — इंदिरानगर या एचएसआर लेआउट? आपके लिए बुक कर देती हूँ।

**user** [hi]: मीना गुप्ता के लिए, स्किन की डॉक्टर से दिखाना है। Monday 17 August शाम को हो पाएगा क्या?

**agent** [hi]: मीना गुप्ता के लिए सोमवार, 17 अगस्त शाम को Dr. Meera Shridhar से इंदिरानगर में 5 बजे, 5:15 या 5:30 पर स्लॉट मिल सकता है। क्या 5 बजे का समय बुक कर दूँ? फीस आठ सौ रुपये रहेगी।

**user** [hi]: हाँ, जो पहला स्लॉट है वही पक्का कर दीजिए।

**agent** [hi]: मीना गुप्ता के लिए सोमवार, 17 अगस्त शाम 5 बजे Dr. Meera Shridhar के पास Apollo Clinic इंदिरानगर में अपॉइंटमेंट बुक हो गया है। फीस आठ सौ रुपये रहेगी। कोई और मदद चाहिए आपको?

## Tool calls
- `get_availability` {"specialty": "Dermatology", "doctor_name": null, "branch": null, "date_from": "2026-08-17", "date_to": "2026-08-17", "weekdays": null, "after_time": "15:00", "before_time": null, "near_time": null, "earliest": false}
- `book_appointment` {"patient_full_name": "Meena Gupta", "doctor_name": "Dr. Meera Shridhar", "branch": "Apollo Clinic Indiranagar", "date": "2026-08-17", "start_time": "17:00", "reason": null, "patient_phone": "+919810000007"}