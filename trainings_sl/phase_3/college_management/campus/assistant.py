"""Read-only, deterministic campus help; no external model or API calls."""

import re
from difflib import get_close_matches
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from .models import Attendance, Department, Fee
from .services import RESOURCES


TOPICS = {
    "students": ("student", "students", "pupil", "pupils", "learner", "learners"),
    "faculty": ("faculty", "faculties", "teacher", "teachers", "professor", "professors", "instructor", "instructors", "lecturer", "lecturers"),
    "departments": ("department", "departments", "division", "divisions"),
    "courses": ("course", "courses", "class", "classes", "subject", "subjects"),
    "enrollments": ("enrollment", "enrollments", "enrolment", "enrolments", "registration", "registrations"),
    "attendance": ("attendance", "attendances", "absent", "present"),
    "fees": ("fee", "fees", "payment", "payments", "tuition", "balance", "balances", "outstanding", "overdue"),
}
LABELS = {"faculty": "Faculty", "fees": "Fees & payments", **{key: key.title() for key in TOPICS if key not in ("faculty", "fees")}}
GUIDES = {
    "students": "To add a student, open Students and choose Add student. Enter the student ID, name, email, department, year, and status, then save. Contact numbers are optional and must contain exactly 10 digits.",
    "faculty": "To add a faculty member, open Faculty and choose Add faculty member. Enter the employee ID, name, email, department, and academic title, then save. Optional contact numbers must contain exactly 10 digits.",
    "departments": "To add a department, open Departments and choose Add department. Enter a unique department name and code, then save. Create departments before adding people or courses.",
    "courses": "To add a course, open Courses and choose Add course. Enter a unique code, name, department, credits, and seats per semester. An instructor is optional. Capacity cannot be reduced below current enrollment.",
    "enrollments": "To enroll a student, open Enrollments and choose Add enrollment. Select an active student and a course, use a consistent semester label, and save. Course capacity is checked per semester; duplicate student/course/semester combinations are blocked.",
    "attendance": "To record attendance, open Attendance and choose Add attendance record. Select an enrollment, date, and status. Future dates, duplicate enrollment/date records, and dropped enrollments are rejected.",
    "fees": "To add or update a fee, open Fees & payments and choose Add fee or edit an existing fee. Select a student, description, total, amount paid, and due date. Amount paid is the cumulative amount received, not an extra payment; it cannot exceed the total.",
}
ALIASES = {
    "gud": "good", "gd": "good", "mrning": "morning", "mornin": "morning",
    "evenin": "evening", "nite": "night", "wanna": "want", "wan": "want",
    "plz": "please", "pls": "please", "u": "you", "ur": "your",
    "wht": "what", "whats": "what", "howmany": "many",
    "attendence": "attendance", "attendace": "attendance",
    "balence": "balance", "studnt": "student", "studnts": "students",
    "facilty": "faculty", "faculity": "faculty", "deparment": "department",
    "departmnt": "department", "cours": "course", "enrolment": "enrollment",
    "enrolments": "enrollments", "paymnt": "payment", "pymnt": "payment",
    "summery": "summary", "overveiw": "overview", "atendence": "attendance",
}
INTENT_WORDS = {
    "how", "help", "steps", "guide", "explain", "export", "csv", "contact",
    "phone", "number", "open", "navigate", "go", "show", "view", "see",
    "check", "list", "display", "count", "counts", "many", "much", "total",
    "distribution", "breakdown", "summary", "overview", "dashboard", "rate",
    "delete", "remove", "update", "change", "create", "add", "enroll",
    "pay", "record", "edit", "modify", "want", "need", "like", "please",
    "good", "morning", "afternoon", "evening", "night", "hello", "hey",
    "hi", "thanks", "thank", "bye", "doing", "feel", "what", "why",
    "know", "can", "could", "would", "is", "are", "there", "today", "me",
}
FUZZY_WORDS = set(INTENT_WORDS)
for _aliases in TOPICS.values():
    FUZZY_WORDS.update(_aliases)


def understand(message):
    normalized = message.casefold().replace("&", " and ")
    normalized = re.sub(r"\bwhat['’]s\b", "what is", normalized)
    words = re.findall(r"[a-z]+|\d+", normalized)
    corrected = [ALIASES.get(word, word) for word in words]
    for index, word in enumerate(corrected):
        if word in ALIASES or len(word) < 4:
            continue
        closest = get_close_matches(word, FUZZY_WORDS, n=1, cutoff=0.82)
        if closest:
            corrected[index] = closest[0]
    words = set(corrected)

    topics = []
    for topic, aliases in TOPICS.items():
        if any(set(re.findall(r"[a-z]+", alias)).issubset(words) for alias in aliases):
            topics.append(topic)
    return words, topics


def reply(message):
    words, topics = understand(message)

    def result(text, destinations=()):
        return {
            "reply": text,
            "links": [{"label": LABELS.get(key, "Overview"), "page": key} for key in destinations],
            "mode": "local",
        }

    greetings = words.intersection({"hi", "hello", "hey", "good", "morning", "afternoon", "evening", "night"})
    asks_how = words.intersection({"how", "help", "steps", "guide", "explain"})
    asks_how_many = words.intersection({"many", "much", "count", "counts", "total"})
    actions = words.intersection({"delete", "remove", "update", "change", "create", "add", "enroll", "pay", "record", "edit", "modify"})
    asks_how_to = (asks_how and not asks_how_many) or (actions and words.intersection({"want", "need", "like", "please"}))
    asks_to_view = words.intersection({"show", "see", "view", "check", "list", "display", "open", "navigate", "go"})

    if "bye" in words and not topics:
        return result("Goodbye! Your campus workspace is ready whenever you need it.", ["dashboard"])

    if actions and not asks_how_to:
        action_topics = topics or ["dashboard"]
        if words.intersection({"delete", "remove"}):
            text = "I cannot delete records in chat. Open the relevant management screen to review and delete a record; records with linked data must be unlinked first."
        elif "pay" in words:
            text = "I cannot process payments. Open Fees & payments and update Amount paid with the cumulative total received; it cannot exceed the fee total."
        elif topics and actions.intersection({"update", "change", "edit", "modify"}):
            text = "I cannot edit records in chat. Open the relevant management screen and use the edit button on the record you want to update."
        elif topics:
            instructions = "\n\n".join(GUIDES[topic] for topic in topics)
            text = f"I cannot change records directly, but I can guide you.\n\n{instructions}"
        else:
            text = "I cannot change records directly. Ask how to update a student, course, fee, or other campus record."
        return result(text, action_topics)

    if asks_how_to:
        if words.intersection({"export", "csv"}):
            answer = "Open a management screen and select Export all CSV. It exports every record of that type, not only the current page or search results."
            return result(answer, topics or ["students"])
        if words.intersection({"contact", "phone", "number"}) and not topics:
            return result("Student and faculty contact numbers are optional. If supplied, use exactly 10 digits (0-9), with no country code, spaces, or punctuation.", ["students", "faculty"])
        if topics:
            prefix = "Sure—here’s how:\n\n" if greetings else ""
            return result(prefix + "\n\n".join(GUIDES[topic] for topic in topics), topics)

    if asks_to_view and topics and not (asks_how_many or words.intersection({"balance", "balances", "outstanding", "overdue", "rate", "summary", "distribution", "breakdown"})):
        prefix = "Good to hear from you! " if greetings else ""
        return result(prefix + "I cannot display individual records in chat, but you can open the management screen here.", topics)

    if "fees" in topics:
        totals = Fee.objects.aggregate(total=Sum("amount_cents", default=0), paid=Sum("paid_cents", default=0))
        overdue = Fee.objects.filter(due_date__lt=timezone.localdate(), paid_cents__lt=F("amount_cents")).count()

        def dollars(cents):
            return f"${Decimal(cents) / 100:,.2f}"

        answer = (
            f"All recorded fees (USD):\nTotal billed: {dollars(totals['total'])}\n"
            f"Collected: {dollars(totals['paid'])}\nOutstanding: {dollars(totals['total'] - totals['paid'])}\n"
            f"Overdue unpaid fee records: {overdue}.\nThese are recorded balances, not payment processing."
        )
        return result(answer, ["fees"])

    if "attendance" in topics and words.intersection({"rate", "how", "what", "summary", "many", "much", "count", "counts", "total", "today", "doing"}):
        totals = Attendance.objects.aggregate(total=Count("pk"), attended=Count("pk", filter=Q(status__in=("Present", "Late"))))
        if not totals["total"]:
            return result("No attendance has been recorded yet. Record attendance against an enrollment to see a rate.", ["attendance"])
        rate = totals["attended"] / totals["total"] * 100
        return result(
            f"Attendance rate: {rate:.0f}% across all semesters "
            f"({totals['attended']} present or late out of {totals['total']} records). "
            "Absent and excused records remain in the denominator.",
            ["attendance"],
        )

    if "departments" in topics and words.intersection({"distribution", "breakdown"}):
        rows = Department.objects.annotate(total=Count("student")).order_by("name")
        lines = [f"{row.name}: {row.total} students" for row in rows]
        return result("\n".join(lines) if lines else "No departments have been added yet.", ["departments"])

    if topics or words.intersection({"summary", "overview", "dashboard", "counts"}):
        selected = topics or list(TOPICS)
        lines = [f"{LABELS[key]}: {RESOURCES[key][0].objects.count()}" for key in selected]
        prefix = "Sure! " if greetings else ""
        return result(prefix + "Current campus record counts (all semesters):\n" + "\n".join(lines), selected)

    if greetings:
        return result(
            "Hello! I’m your campus assistant. I’m doing well, thanks for asking! "
            "I can chat about live campus counts, attendance, fee balances, or how to use the app. "
            "I’m a local rule-based assistant, not a generative AI, so I can’t change records or answer general knowledge questions.",
            ["dashboard"],
        )

    return result(
        "I’m not sure I understood that. You can ask conversationally, for example: "
        "'Can you show attendence?', 'How many studnts are there?', "
        "'What is the fee balence?', or 'I want to add a student'. "
        "I use local rules, not a general-purpose AI model, and I don’t look up individual student or faculty details.",
        ["dashboard"],
    )
