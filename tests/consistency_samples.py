"""Natural-language samples for the cross-modal semantic-consistency tests
(and for re-checking the threshold in app/evaluator/semantic_consistency.py
by hand). Two projects: a library book-loan system and a weather station."""

LIBRARY_CODE = '''
"""Library loan manager: tracks which member has borrowed which book,
computes due dates and charges overdue fines."""

from datetime import date, timedelta

LOAN_DAYS = 14  # standard loan period in days


class Library:
    """Keeps the catalogue of books and the active loans of members."""

    def __init__(self):
        self.books = {}
        self.loans = {}

    def borrow(self, member, isbn, today):
        """Lend a book to a member and return the date it is due back.

        Raises ValueError if the book is already on loan.
        """
        if isbn in self.loans:
            raise ValueError("already borrowed")
        # remember who has the book and when it must be returned
        self.loans[isbn] = (member, today + timedelta(days=LOAN_DAYS))
        return self.loans[isbn][1]

    def return_book(self, isbn, today):
        """Close the loan and compute the overdue fine, if any."""
        member, due = self.loans.pop(isbn)
        late_days = max(0, (today - due).days)
        # fine is 50 cents per day late, capped at 20 dollars
        return min(20.0, 0.5 * late_days)
'''

LIBRARY_REPORT = """
1. Introduction
This report describes our library loan management system. The program keeps
a catalogue of books and records which member has borrowed each book.

2. Design
When a member borrows a book, the system stores the loan and calculates the
due date, which is fourteen days after the borrowing date. A book that is
already on loan cannot be borrowed again. When the book is returned, the loan
is closed and an overdue fine is calculated: members pay fifty cents for every
day the book is late, up to a maximum of twenty dollars.

3. Testing
We tested borrowing, returning on time, and returning late, and checked that
fines are capped correctly.
"""

# Same content, deliberately different wording and vocabulary.
LIBRARY_REPORT_PARAPHRASED = """
Our project is software for a lending library. It remembers every title in the
collection and who currently has it checked out. Checking out an item sets a
return deadline two weeks later, and an item that is already out cannot be
checked out a second time. Bringing an item back ends the lending record and
charges a late penalty of half a dollar per overdue day, never more than
twenty dollars in total. We verified on-time and late returns and the penalty
limit.
"""

LIBRARY_TRANSCRIPT = """
hi everyone, in this video I'll demo our library system. so here I add a few
books to the catalogue, and now Alice borrows this book, and you can see the
due date is two weeks from today. if Bob tries to borrow the same book it
refuses because it's already on loan. now Alice returns it five days late and
the fine comes out as two dollars fifty, and if it's really late the fine
stops at twenty dollars. that's the main functionality, thanks for watching.
"""

WEATHER_REPORT = """
1. Introduction
This report presents a weather station dashboard that collects temperature,
humidity and rainfall readings from outdoor sensors every ten minutes.

2. Method
Sensor readings are sent over Wi-Fi to a Raspberry Pi, which stores them and
plots daily temperature curves and weekly rainfall totals. We compared our
readings against the national meteorological service and found the
temperature sensor drifted by about half a degree in direct sunlight.

3. Conclusion
A radiation shield improved accuracy. Future work includes wind speed.
"""

WEATHER_TRANSCRIPT = """
okay so this is our weather station. the sensor box is outside on the balcony
and it sends temperature and humidity every ten minutes to the raspberry pi.
here's the dashboard, you can see today's temperature curve and the rainfall
for the week. we noticed in direct sun the temperature reads a bit high so we
built a little shield for it.
"""


def long_text(base: str, sections: int = 25) -> str:
    """A long document built from numbered repeats of one topic -- long
    enough to need many model-sized chunks."""
    return "\n\n".join(f"Section {i + 1}. {base.strip()}" for i in range(sections))
