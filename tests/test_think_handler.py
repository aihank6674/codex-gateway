import os
import sys

# Ensure engine is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.think_handler import ThinkStreamFilter

def test_discard_think_blocks():
    """
    Tests that inside code completion mode, the <think>...</think> block is completely discarded.
    """
    stream_filter = ThinkStreamFilter(discard_think=True)
    chunks = [
        "def subtract(a, b):\n    ",
        "<think>",
        "\nAnalyzing subtraction operation.\n",
        "Need to return a minus b.\n",
        "</think>",
        "return a - b"
    ]
    results = []
    for chunk in chunks:
        out = stream_filter.process(chunk)
        if out:
            results.append(out)
    
    assert "".join(results) == "def subtract(a, b):\n    return a - b"

def test_format_think_blocks():
    """
    Tests that inside chat mode, the <think>...</think> block is formatted into a Markdown blockquote.
    """
    stream_filter = ThinkStreamFilter(discard_think=False)
    chunks = [
        "Here is the answer:\n",
        "<think>",
        "Let me explain subtraction.",
        "</think>",
        "\nHope this helps!"
    ]
    results = []
    for chunk in chunks:
        out = stream_filter.process(chunk)
        if out:
            results.append(out)
    
    full_output = "".join(results)
    assert "Here is the answer:\n" in full_output
    assert "> [!NOTE]" in full_output
    assert "💭 *Thinking process:*" in full_output
    assert "Let me explain subtraction." in full_output
    assert "Hope this helps!" in full_output

def test_partial_tag_buffering():
    """
    Tests that partial tags like '<thi' at the end of a chunk are buffered and not output immediately.
    """
    stream_filter = ThinkStreamFilter(discard_think=True)
    
    # 1. Output before tag
    assert stream_filter.process("hello ") == "hello "
    
    # 2. Output partial start tag
    assert stream_filter.process("<thi") == ""
    
    # 3. Complete start tag
    assert stream_filter.process("nk>hidden block") == ""
    
    # 4. Partial end tag
    assert stream_filter.process("</thi") == ""
    
    # 5. Complete end tag and final output
    assert stream_filter.process("nk> world") == " world"
