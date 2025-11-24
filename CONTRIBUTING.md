# Contributing to SquidStats

Thank you for your interest in contributing to SquidStats! This document provides guidelines and instructions for contributing to the project.

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Git
- A Squid proxy server (for testing)

### Setting up the Development Environment

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/SquidStats.git
   cd SquidStats
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

## Code Quality Standards

We maintain high code quality standards using automated tools:

### Linting with Ruff

```bash
# Check for linting issues
ruff check .

# Fix auto-fixable issues
ruff check --fix .

# Format code
ruff format .
```

### Type Checking with MyPy

```bash
mypy . --ignore-missing-imports
```

### Security Scanning

```bash
bandit -r . -x tests/
safety check -r requirements.txt
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_specific.py
```

### Writing Tests

- Write tests for new features and bug fixes
- Use pytest for testing framework
- Place tests in the `tests/` directory
- Follow the naming convention `test_*.py`

## Pull Request Process

1. **Fork the repository** and create your feature branch
   ```bash
   git checkout -b feature/amazing-feature
   ```

2. **Make your changes** following the code style guidelines

3. **Add tests** for your changes if applicable

4. **Run the full test suite** to ensure nothing breaks
   ```bash
   pytest
   ruff check .
   mypy . --ignore-missing-imports
   ```

5. **Commit your changes** with a clear commit message
   ```bash
   git commit -m "Add amazing feature: brief description"
   ```

6. **Push to your fork** and create a pull request
   ```bash
   git push origin feature/amazing-feature
   ```

### Pull Request Guidelines

- **Clear description**: Explain what changes you made and why
- **Link issues**: Reference any related issues using `#issue-number`
- **Small changes**: Keep PRs focused and reasonably sized
- **Update documentation**: Update relevant documentation if needed
- **Add tests**: Include tests for new functionality
- **Follow conventions**: Use the established code style and patterns

## Code Style Guidelines

### Python Code Style

- Follow PEP 8 style guidelines
- Use type hints for function parameters and return values
- Write docstrings for classes and functions
- Use meaningful variable and function names
- Keep functions focused and reasonably sized

### Example Code Style

```python
def process_log_entry(log_line: str) -> dict[str, Any]:
    """
    Process a single log entry and extract relevant information.
    
    Args:
        log_line: Raw log line from Squid proxy
        
    Returns:
        Dictionary containing parsed log information
        
    Raises:
        ValueError: If log line format is invalid
    """
    if not log_line.strip():
        raise ValueError("Log line cannot be empty")
    
    # Process the log line
    return {"timestamp": "...", "url": "..."}
```

### HTML/CSS/JavaScript

- Use semantic HTML
- Follow modern CSS practices
- Use Tailwind CSS classes consistently
- Write clean, readable JavaScript
- Add comments for complex logic

## Documentation

### Code Documentation

- Write clear docstrings for all public functions and classes
- Include type hints for parameters and return values
- Document any complex algorithms or business logic
- Update README.md when adding new features

### Inline Comments

- Use comments to explain "why" not "what"
- Keep comments up-to-date with code changes
- Remove outdated or obvious comments

## Issue Reporting

### Bug Reports

When reporting bugs, please include:

- **Clear description** of the issue
- **Steps to reproduce** the problem
- **Expected behavior** vs actual behavior
- **Environment information** (OS, Python version, etc.)
- **Log files** or error messages if applicable

### Feature Requests

For feature requests, please include:

- **Clear description** of the proposed feature
- **Use case** or motivation for the feature
- **Possible implementation** ideas if you have them
- **Examples** of how the feature would be used

## Getting Help

- **GitHub Issues**: For bugs, feature requests, and general questions
- **Discussions**: For broader topics and community discussion
- **Code Review**: Don't hesitate to ask for feedback on your PRs

## Code of Conduct

Please note that this project adheres to a Code of Conduct. By participating, you are expected to uphold this code:

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Respect different opinions and approaches
- Report unacceptable behavior

Thank you for contributing to SquidStats!
