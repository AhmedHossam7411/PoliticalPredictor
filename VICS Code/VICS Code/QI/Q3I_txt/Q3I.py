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
    words_folder = os.path.join(script_dir, 'Lists Q3I')

    # File paths
    risk_acceptant_file = os.path.join(words_folder, 'risk_acceptant.txt')
    risk_averse_file = os.path.join(words_folder, 'risk_averse.txt')
    input_text_file = os.path.join(base_path, 'input_text.txt')

    # Load words
    acceptant_words = load_words(risk_acceptant_file)
    averse_words = load_words(risk_averse_file)

    # Load input text
    try:
        with open(input_text_file, 'r', encoding='utf-8') as file:
            text = file.read()
    except FileNotFoundError:
        print(f"Error: Input text file not found - {input_text_file}")
        return

    # Count positive and negative words
    acceptant_count = count_words_in_text(text, acceptant_words)
    averse_count = count_words_in_text(text, averse_words)

    # Calculate Nature of Political Universe Index
    tot_count = acceptant_count + averse_count
    sum_IQV_Int= (acceptant_count/tot_count)**2
    sum_IQV_Ext=(averse_count/tot_count)**2
    sum_IQV= sum_IQV_Int+sum_IQV_Ext
    IQV = 2*(1-sum_IQV)
    risk_orientation_value = 1-IQV

    # Output results
    print(f"Risk Acceptant words count: {acceptant_count}")
    print(f"Risk Averse words count: {averse_count}")
    print(f"Predictability  Index: {risk_orientation_value:.2f}")

# Run the program
if __name__ == "__main__":
    main()
