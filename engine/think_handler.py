class ThinkStreamFilter:
    """
    Parser for filtering/formatting streaming text blocks enclosed in <think>...</think> tags.
    """
    def __init__(self, discard_think: bool = True):
        """
        :param discard_think: If True, the text within <think>...</think> is completely discarded (ideal for code completion).
                              If False, it converts the think block into an elegant Markdown note (ideal for chat).
        """
        self.discard_think = discard_think
        self.in_think = False
        self.buffer = ""

    def process(self, chunk: str) -> str:
        """
        Processes a single string chunk from the SSE stream and handles buffering and think parsing.
        """
        self.buffer += chunk
        output = []

        while self.buffer:
            if not self.in_think:
                # 1. Look for the start tag "<think>"
                idx = self.buffer.find("<think>")
                if idx != -1:
                    # Append everything before the tag to output
                    output.append(self.buffer[:idx])
                    self.in_think = True
                    
                    if not self.discard_think:
                        # Format the start of a thinking block for Markdown chat
                        output.append("\n> [!NOTE]\n> 💭 *Thinking process:*\n> ")
                    
                    # Consume buffer up to after "<think>"
                    self.buffer = self.buffer[idx + len("<think>"):]
                else:
                    # Look if there is a partial start tag at the very end of the buffer (e.g. "<thin")
                    potential_start = "<think>"
                    matched_len = 0
                    for i in range(1, len(potential_start)):
                        if self.buffer.endswith(potential_start[:i]):
                            matched_len = i
                            break
                    
                    if matched_len > 0:
                        # Output everything except the partial tag, keep partial tag in buffer
                        output.append(self.buffer[:-matched_len])
                        self.buffer = self.buffer[-matched_len:]
                        break
                    else:
                        # No tags or partial tags found, consume full buffer
                        output.append(self.buffer)
                        self.buffer = ""
            else:
                # 2. Inside the think block, look for the end tag "</think>"
                idx = self.buffer.find("</think>")
                if idx != -1:
                    think_content = self.buffer[:idx]
                    if not self.discard_think:
                        # Format think lines into Markdown blockquote
                        formatted = think_content.replace("\n", "\n> ")
                        output.append(formatted + "\n\n")
                    
                    self.in_think = False
                    self.buffer = self.buffer[idx + len("</think>"):]
                else:
                    # Look if there is a partial end tag at the end of the buffer (e.g. "</thin")
                    potential_end = "</think>"
                    matched_len = 0
                    for i in range(1, len(potential_end)):
                        if self.buffer.endswith(potential_end[:i]):
                            matched_len = i
                            break
                    
                    if matched_len > 0:
                        # Process everything before the partial end tag
                        in_block = self.buffer[:-matched_len]
                        if not self.discard_think:
                            output.append(in_block.replace("\n", "\n> "))
                        self.buffer = self.buffer[-matched_len:]
                        break
                    else:
                        # Still in the middle of thinking, process/consume everything
                        if not self.discard_think:
                            output.append(self.buffer.replace("\n", "\n> "))
                        self.buffer = ""
                        break

        return "".join(output)
