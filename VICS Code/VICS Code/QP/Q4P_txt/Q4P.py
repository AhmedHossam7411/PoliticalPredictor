import re
import os
from collections import Counter

# Function to load words from a file
def load_words(file_path):
    """Load words from a file into a set for fast lookup."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return set(file.read().splitlines())  # Read lines and strip newlines
    except FileNotFoundError:
        print(f"Warning: File not found - {file_path}")
        return set()

# Function to count word occurrences in a text
def count_words_in_text(text, words):
    """Count occurrences of words in text using regex and Counter."""
    word_pattern = re.compile(r'\b\w+\b', re.IGNORECASE)
    text_words = word_pattern.findall(text.lower())  # Tokenize text
    word_counts = Counter(text_words)  # Count occurrences of each word

    # Count each occurrence of the words in the set
    total_count = 0
    for word in words:
        count = word_counts[word.lower()]
        if count > 0:
            total_count += count
    return total_count

# Main function
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.normpath(os.path.join(script_dir, '..', '..'))
    words_folder = script_dir

    # File paths
    self_attributions_file = os.path.join(words_folder, 'self_attributions.txt')
    other_attributions_file = os.path.join(words_folder, 'other_attributions.txt')
    input_text_file = os.path.join(base_path, 'input_text.txt')

    # Load words
    self_words = load_words(self_attributions_file)
    other_words = load_words(other_attributions_file)

    # Load input text
    try:
        with open(input_text_file, 'r', encoding='utf-8') as file:
            text = file.read()
    except FileNotFoundError:
        print(f"Error: Input text file not found - {input_text_file}")
        return

    # Count positive and negative words
    self_count = count_words_in_text(text, self_words)
    other_count = count_words_in_text(text, other_words)

    # Calculate Nature of Political Universe Index
    total_words = self_count + other_count
    index = self_count / total_words if total_words else 0.0

    # Output results
    print(f"Self Attributions words count: {self_count}")
    print(f"Other Attributions count: {other_count}")
    print(f"Control Over Historical Development Index: {index:.2f}")

# Run the program
if __name__ == "__main__":
    main()
