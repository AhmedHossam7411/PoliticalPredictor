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
    words_folder = os.path.join(script_dir, 'Lists Q4I')

    # File paths
    positive_words_file = os.path.join(words_folder, 'positive_words.txt')
    negative_words_file = os.path.join(words_folder, 'negative_words.txt')
    input_text_file = os.path.join(base_path, 'input_text.txt')

    # Load words
    positive_words = load_words(positive_words_file)
    negative_words = load_words(negative_words_file)

    # Load input text
    try:
        with open(input_text_file, 'r', encoding='utf-8') as file:
            text = file.read()
    except FileNotFoundError:
        print(f"Error: Input text file not found - {input_text_file}")
        return

    # Count positive and negative words
    positive_count = count_words_in_text(text, positive_words)
    negative_count = count_words_in_text(text, negative_words)

    # Calculate Nature of Political Universe Index
    total_words = positive_count + negative_count
    PP=positive_count/total_words
    NP=negative_count/total_words
    PD=abs(PP-NP)
    index = 1-PD


    # Output results
    print(f"Positive Self-Attributions words count: {positive_count}")
    print(f"Negative Self-Attributions words count: {negative_count}")
    print(f"Shift Propensity Index: {index:.2f}")

# Run the program
if __name__ == "__main__":
    main()
