from aidycai.infrastructure.analyzers.python_ast import PythonAstAnalyzer

SOURCE = '''
from tax import calculate_tax
import json

TAX_RATE = 19

def standalone():
    helper()
    return 1

def helper():
    return 1

class Invoice:
    """doc"""

    def __init__(self, amount):
        self.amount = amount

    def calculate_total(self, extra=0):
        return self.amount + extra

    @staticmethod
    def empty():
        return Invoice(0)

class InvoiceService(Invoice):
    async def create_invoice(self):
        return Invoice(1)
'''


def test_extracts_classes_functions_methods_imports_and_constants():
    analysis = PythonAstAnalyzer().analyze("billing/invoice.py", SOURCE)
    types = {item.type: [] for item in analysis.symbols}
    for item in analysis.symbols:
        types.setdefault(item.type, []).append(item)

    class_names = {item.qualified_name for item in analysis.symbols if item.type == "class"}
    assert "Invoice" in class_names
    assert "InvoiceService" in class_names

    methods = {item.qualified_name: item for item in analysis.symbols if item.type == "method"}
    assert "Invoice.calculate_total" in methods
    assert "Invoice.__init__" in methods
    assert "Invoice.empty" in methods
    assert methods["Invoice.calculate_total"].metadata["params"] == ["self", "extra"]
    assert methods["InvoiceService.create_invoice"].metadata["async"] is True
    assert methods["Invoice.empty"].metadata["decorators"] == ["staticmethod"]

    functions = {item.name: item for item in analysis.symbols if item.type == "function"}
    assert "standalone" in functions
    assert "helper" in functions
    assert functions["standalone"].metadata["calls"] == ["helper"]

    constants = {item.name for item in analysis.symbols if item.type == "constant"}
    assert "TAX_RATE" in constants

    modules = [item for item in analysis.symbols if item.type == "module"]
    assert modules[0].name == "invoice"

    imported = {(item.import_type, item.module) for item in analysis.imports}
    assert ("from", "tax") in imported
    assert ("import", "json") in imported

    invoice = next(item for item in analysis.symbols if item.qualified_name == "Invoice")
    assert invoice.line_start is not None
    assert invoice.line_end is not None
    assert invoice.line_end >= invoice.line_start
