# earliest_cross_branch_en (PASS)

**agent** [en]: Hello! Apollo Clinic, Indiranagar and HSR Layout — this is Asha. How may I help you?

**user** [en]: What's the earliest dermatology appointment you have on Wednesday 19 August? Any branch works for me.

**agent** [en]: The earliest dermatology appointment on Wednesday, nineteenth August is at eleven in the morning with Dr. Tejashwini S M at Apollo Clinic HSR Layout. Would you like to book this slot? If you prefer a little later, I have eleven fifteen and eleven thirty as well.

**user** [en]: Great, book that one. Kavya Nair.

**agent** [en]: Your appointment is booked for Kavya Nair with Dr. Tejashwini S M, Wednesday, nineteenth August, eleven in the morning at Apollo Clinic HSR Layout. The fee is seven hundred rupees. Anything else I can help you with?

## Tool calls
- `get_availability` {"specialty": "Dermatology", "doctor_name": null, "branch": null, "date_from": "2026-08-19", "date_to": "2026-08-19", "weekdays": null, "after_time": null, "before_time": null, "near_time": null, "earliest": true}
- `book_appointment` {"patient_full_name": "Kavya Nair", "doctor_name": "Dr. Tejashwini S M", "branch": "hsr", "date": "2026-08-19", "start_time": "11:00", "reason": null, "patient_phone": "+919810000005"}