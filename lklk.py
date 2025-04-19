import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import csv
import os
import re
import json
from datetime import datetime, timezone

# ========== Настройки True Tabs и Telegram Bot ===========
API_TOKEN         = '7157619299:AAGzXLUWQaNleeHiULr4s-zhqtFtzQ0aONE'
TRUE_TABS_WEBHOOK = 'https://true.tabs.sale/fusion/v1/datasheets/dst4tjJSjQ4lVVfKtz/records'
TRUE_TABS_GET     = TRUE_TABS_WEBHOOK
HEADERS           = {'Authorization': 'Bearer uskuKABYCLzpEBhKQrRCI4O'}

bot = telebot.TeleBot(API_TOKEN)

# Контексты: создание анкеты и редактирование найденных записей
user_data    = {}  # {uid: {step:int, data:dict, editing_field:Optional[str]}}
edit_context = {}  # {uid: {record_id:str, field:Optional[str]}}

# Порядок и подсказки полей
fields_sequence = [
    "Фамилия","Имя","Отчество","Пол","Дата рождения",
    "Номер телефона","Электронная почта","Номер паспорта",
    "Номер СНИЛС","Номер пропуска","Компания",
    "Тема обращения","Текст запроса"
]
prompts = {
    "Фамилия":           "Введите фамилию (только буквы):",
    "Имя":               "Введите имя (только буквы):",
    "Отчество":          "Введите отчество (только буквы):",
    "Пол":               "Укажите пол (М или Ж):",
    "Дата рождения":     "Введите дату рождения (ГГГГ-ММ-ДД):",
    "Номер телефона":    "Введите телефон (10–15 цифр):",
    "Электронная почта": "Введите e‑mail:",
    "Номер паспорта":    "Введите паспорт (10 цифр):",
    "Номер СНИЛС":       "Введите СНИЛС (11 цифр):",
    "Номер пропуска":    "Введите пропуск (только цифры):",
    "Компания":          "Введите компанию:",
    "Тема обращения":    "Введите тему обращения:",
    "Текст запроса":     "Опишите запрос подробно:"
}

# ========== Валидация и чистка данных ===========
def clean_snils(v):
    return re.sub(r'\D','', v)
def validate_snils(v):
    return bool(re.fullmatch(r'(?!0{11})\d{11}', clean_snils(v)))
def clean_phone(v):
    return re.sub(r'[^\d]','', v)
def validate_phone(v):
    return bool(re.fullmatch(r'\d{10,15}', clean_phone(v)))

def validate(field, val):
    if field in ("Фамилия","Имя","Отчество"):
        return bool(re.fullmatch(r"[А-ЯЁ][а-яё]+", val))
    if field == "Пол":
        return val in ("М","Ж")
    if field == "Дата рождения":
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return True
        except:
            return False
    if field == "Номер телефона":
        return validate_phone(val)
    if field == "Электронная почта":
        return bool(re.fullmatch(r".+@.+\..+", val))
    if field == "Номер паспорта":
        return bool(re.fullmatch(r"\d{10}", val))
    if field == "Номер СНИЛС":
        return validate_snils(val)
    if field == "Номер пропуска":
        return val.isdigit()
    return bool(val.strip())

# ========== Логирование ===========
log_file = "log_full.csv"
if not os.path.exists(log_file):
    with open(log_file, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["Дата","Telegram ID"] + fields_sequence)

# ========== Анкета: запуск и шаги ===========
@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.chat.id
    user_data[uid] = {"step":0, "data":{}, "editing_field": None}
    ask_field(uid)


def ask_field(uid):
    step = user_data[uid]["step"]
    field = fields_sequence[step]
    if field == "Пол":
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("М", callback_data="Пол|М"),
            InlineKeyboardButton("Ж", callback_data="Пол|Ж")
        )
        bot.send_message(uid, prompts[field], reply_markup=kb)
    else:
        bot.send_message(uid, prompts[field])

# ========== Специальные хендлеры для редактирования найденных записей ===========
@bot.callback_query_handler(func=lambda c: c.data.startswith("EDITREC"))
def handle_editrec(c):
    bot.answer_callback_query(c.id)
    uid = c.message.chat.id
    rec_id = c.data.split("|",1)[1]
    edit_context[uid] = {"record_id": rec_id, "field": None}
    kb = InlineKeyboardMarkup(row_width=1)
    for fld in fields_sequence:
        kb.add(InlineKeyboardButton(fld, callback_data=f"EDITFIELDREC|{fld}"))
    bot.send_message(uid, "Выберите поле для редактирования:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("EDITFIELDREC"))
def handle_editfieldrec(c):
    bot.answer_callback_query(c.id)
    uid = c.message.chat.id
    fld = c.data.split("|",1)[1]
    edit_context[uid]["field"] = fld
    bot.send_message(uid, f"Введите новое значение для «{fld}»:")

@bot.message_handler(func=lambda m: m.chat.id in edit_context and edit_context[m.chat.id]["field"] is not None)
def handle_text_editrec(m):
    uid = m.chat.id
    ctx = edit_context.pop(uid)
    rec_id = ctx["record_id"]
    field  = ctx["field"]
    new_val = m.text.strip()
    # валидация и конверсия
    if not validate(field, new_val):
        return bot.send_message(uid, f"❌ Некорректно для «{field}». Попробуйте снова.")
    if field == "Номер СНИЛС":
        new_val = int(clean_snils(new_val))
    elif field in ("Номер паспорта","Номер пропуска"):
        new_val = int(new_val)
    elif field == "Дата рождения":
        dt = datetime.strptime(new_val, "%Y-%m-%d")
        new_val = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif field == "Номер телефона":
        new_val = clean_phone(new_val)
    # PATCH запрос
    payload = {"records":[{"recordId": rec_id, "fields": {field: new_val}}]}
    try:
        res = requests.patch(TRUE_TABS_WEBHOOK, json=payload, headers=HEADERS).json()
        if res.get("success"):
            bot.send_message(uid, f"✅ Поле «{field}» обновлено.")
        else:
            bot.send_message(uid, f"⚠️ Ошибка: {res.get('message')}")
    except Exception as e:
        bot.send_message(uid, f"❌ Ошибка при обновлении: {e}")

# ========== Общий хендлер inline для анкеты ===========
@bot.callback_query_handler(func=lambda call: True)
def on_inline(call):
    uid = call.message.chat.id
    bot.answer_callback_query(call.id)
    # проверка только анкеты, не search-edit
    if uid not in user_data:
        bot.send_message(uid, "❗ Сначала /start")
        return
    action, *rest = call.data.split("|",1)
    if action == "Пол":
        user_data[uid]["data"]["Пол"] = rest[0]
        user_data[uid]["step"] += 1
        ask_field(uid)
        return
    if action == "CONFIRM":
        send_to_truetabs(uid)
        return
    if action == "EDIT":
        # редактировать анкету
        kb = InlineKeyboardMarkup(row_width=1)
        for fld in fields_sequence:
            kb.add(InlineKeyboardButton(fld, callback_data=f"EDITFIELD|{fld}"))
        bot.send_message(uid, "Выберите поле для редактирования:", reply_markup=kb)
        return
    if action == "EDITFIELD":
        fld = rest[0]
        user_data[uid]["editing_field"] = fld
        bot.send_message(uid, f"Введите новое значение для «{fld}»:")
        return

# ========== Текстовые ответы для анкеты ===========
@bot.message_handler(func=lambda m: m.chat.id in user_data)
def on_text(m):
    uid = m.chat.id
    state = user_data[uid]
    # редактируем поле анкеты
    if state.get("editing_field"):
        fld = state.pop("editing_field")
        val = m.text.strip()
        if not validate(fld, val):
            bot.send_message(uid, f"❌ Некорректно для «{fld}». Попробуйте еще.")
            return
        if fld == "Номер СНИЛС":    val = clean_snils(val)
        if fld == "Номер телефона": val = clean_phone(val)
        state["data"][fld] = val
        show_summary(uid)
        return
    # обычная анкета по шагам
    step = state["step"]
    fld  = fields_sequence[step]
    val  = m.text.strip()
    if not validate(fld, val):
        bot.send_message(uid, f"❌ Некорректно для «{fld}». Попробуйте еще.")
        ask_field(uid)
        return
    if fld == "Номер СНИЛС":    val = clean_snils(val)
    if fld == "Номер телефона": val = clean_phone(val)
    state["data"][fld] = val
    if step+1 < len(fields_sequence):
        state["step"] += 1
        ask_field(uid)
    else:
        show_summary(uid)

# ========== Показ summary анкеты и отправка ===========
def show_summary(uid):
    d = user_data[uid]["data"]
    txt = "📋 Ваши текущие данные:\n" + "\n".join(f"• {k}: {d.get(k,'')}" for k in fields_sequence)
    kb  = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Подтвердить", callback_data="CONFIRM"),
        InlineKeyboardButton("✏️ Редактировать", callback_data="EDIT")
    )
    bot.send_message(uid, txt, reply_markup=kb)

# ========== Отправка анкеты в True Tabs ===========
def send_to_truetabs(uid):
    d = user_data[uid]["data"].copy()
    # привести типы
    d["Номер паспорта"] = int(d["Номер паспорта"])
    d["Номер пропуска"] = int(d["Номер пропуска"])
    d["Номер СНИЛС"]    = int(d["Номер СНИЛС"])
    dt = datetime.strptime(d["Дата рождения"], "%Y-%m-%d")
    d["Дата рождения"]   = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"records":[{"fields":d}]}
    res = requests.post(TRUE_TABS_WEBHOOK, json=payload, headers=HEADERS).json()
    if res.get("success"):
        bot.send_message(uid, "✅ Ваши данные отправлены!")
    else:
        bot.send_message(uid, f"⚠️ Ошибка: {res.get('message')}")
    # логирование
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now(), uid] + [d[f] for f in fields_sequence])
    user_data.pop(uid)

# ========== Поиск и детальный просмотр ===========
@bot.message_handler(commands=['search'])
def cmd_search(m):
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        return bot.send_message(m.chat.id, "Используйте: /search <Поле> <Значение>")
    field, value = parts[1], parts[2].strip().lower()
    if field not in fields_sequence:
        return bot.send_message(m.chat.id, "⚠️ Поле не поддерживается: " + ", ".join(fields_sequence))
    recs = requests.get(TRUE_TABS_GET, headers=HEADERS).json().get('data',{}).get('records',[])
    matches = [r for r in recs if str(r['fields'].get(field,'')).lower()==value]
    if not matches:
        return bot.send_message(m.chat.id, "ℹ️ Ничего не найдено.")
    for rec in matches[:5]:
        f = rec['fields']
        raw = f.get('Дата рождения','')
        if isinstance(raw,str):
            date_disp = raw[:10]
        else:
            ts = int(raw)/1000 if raw>1e10 else int(raw)
            date_disp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        txt = (
            f"📋 ID: {rec['recordId']}\n"
            f"• {field}: {f.get(field,'–')}\n"
            f"• Тема: {f.get('Тема обращения','–')}\n"
            f"• Телефон: {f.get('Номер телефона','–')}\n"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("Подробнее", callback_data=f"DETAIL|{rec['recordId']}"),
            InlineKeyboardButton("Редактировать", callback_data=f"EDITREC|{rec['recordId']}")
        )
        bot.send_message(m.chat.id, txt, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("DETAIL"))
def show_detail(c):
    bot.answer_callback_query(c.id)
    rec_id = c.data.split("|",1)[1]
    data = requests.get(f"{TRUE_TABS_GET}/{rec_id}", headers=HEADERS).json().get('data',{})
    fields = data.get('fields',{})
    txt = "🔍 Подробно:\n" + "\n".join(f"• {k}: {fields.get(k,'–')}" for k in fields_sequence)
    bot.send_message(c.message.chat.id, txt)

# Запуск бота
bot.polling()