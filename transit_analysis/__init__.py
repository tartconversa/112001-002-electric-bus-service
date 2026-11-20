"""电动公交运营分析。

按可比的运营区间联合呈现车辆电动化、实际运力、服务可靠性与能源表现，
支持调度方案的提交、校验、影响评估与留存复核。
"""

from .compare import compare_datasets
from .config import AnalysisConfig
from .loader import DatasetError, load_dataset
from .metrics import compute_metrics
from .scenarios import ProposalError, evaluate_proposal, load_proposal, validate_proposal
from .store import list_proposals, load_saved_proposal, save_proposal

__version__ = "0.1.0"

__all__ = [
    "AnalysisConfig",
    "DatasetError",
    "ProposalError",
    "compare_datasets",
    "compute_metrics",
    "evaluate_proposal",
    "list_proposals",
    "load_dataset",
    "load_proposal",
    "load_saved_proposal",
    "save_proposal",
    "validate_proposal",
]
