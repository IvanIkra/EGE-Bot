from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class SM2Result:
    interval: int
    repetitions: int
    ef: float
    next_review: date


def sm2_update(
    quality: int,
    interval: int,
    repetitions: int,
    ef: float,
) -> SM2Result:
    """
    Apply SM-2 algorithm update.

    quality: 5 = correct first try, 3 = correct second try, 1 = wrong
    interval: current interval in days
    repetitions: number of successful repetitions
    ef: easiness factor
    """
    if quality >= 3:
        if repetitions == 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            new_interval = round(interval * ef)
        new_repetitions = repetitions + 1
    else:
        new_interval = 1
        new_repetitions = 0

    new_ef = ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    new_ef = max(new_ef, 1.3)

    next_review = date.today() + timedelta(days=new_interval)

    return SM2Result(
        interval=new_interval,
        repetitions=new_repetitions,
        ef=new_ef,
        next_review=next_review,
    )
