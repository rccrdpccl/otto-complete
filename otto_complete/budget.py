import json
import logging
import os
import threading

log = logging.getLogger(__name__)


class BudgetTracker:
    def __init__(self, max_budget: float, state_file: str):
        self.max_budget = max_budget
        self.state_file = state_file
        self._lock = threading.Lock()
        self._spent = self._load()

    def _load(self) -> float:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    return json.load(f).get("total_spent_usd", 0.0)
            except Exception:
                log.warning("Failed to load budget state, starting from 0")
        return 0.0

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump({"total_spent_usd": self._spent}, f)
        except Exception:
            log.warning("Failed to persist budget state")

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self.max_budget - self._spent)

    def can_spend(self, amount: float = 0.0) -> bool:
        with self._lock:
            return self._spent + amount < self.max_budget

    def record(self, amount: float):
        with self._lock:
            self._spent += amount
            self._save()
            if self._spent >= self.max_budget:
                log.warning("Budget exhausted: $%.2f / $%.2f", self._spent, self.max_budget)
            else:
                log.info("Budget: $%.2f spent, $%.2f remaining",
                         self._spent, self.max_budget - self._spent)
