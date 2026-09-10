import re

file_path = r"C:\src\UnifiParent\src\app\templates\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    html = f.read()

# 1. Dark mode replacements
html = html.replace('class="bg-white rounded-lg', 'class="bg-white dark:bg-gray-800 rounded-lg')
html = html.replace('class="bg-white shadow', 'class="bg-white dark:bg-gray-800 shadow')
html = html.replace('class="bg-gray-50"', 'class="bg-gray-50 dark:bg-gray-700"')
html = html.replace('class="bg-gray-50 p-3', 'class="bg-gray-50 dark:bg-gray-700 p-3')
html = html.replace('bg-white divide-y', 'bg-white dark:bg-gray-800 divide-y')
html = html.replace('divide-gray-200', 'divide-gray-200 dark:divide-gray-700')
html = html.replace('text-gray-900', 'text-gray-900 dark:text-gray-100')
html = html.replace('text-gray-800', 'text-gray-800 dark:text-gray-200')
html = html.replace('text-gray-700', 'text-gray-700 dark:text-gray-300')
html = html.replace('text-gray-600', 'text-gray-600 dark:text-gray-400')
html = html.replace('text-gray-500', 'text-gray-500 dark:text-gray-400')
html = html.replace('border-gray-200', 'border-gray-200 dark:border-gray-600')
html = html.replace('border-gray-300', 'border-gray-300 dark:border-gray-600')
html = html.replace('bg-blue-50 ', 'bg-blue-50 dark:bg-blue-900 ')
html = html.replace('border-blue-100', 'border-blue-100 dark:border-blue-800')
html = html.replace('bg-gray-100 hover:bg-gray-200', 'bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600')

# Forms/Inputs
html = re.sub(r'class="([^"]*?)border([^"]*?)"', lambda m: f'class="{m.group(1)}border dark:border-gray-600 dark:bg-gray-700{m.group(2)}"', html)

# Fix some input text colors
html = html.replace('class="mt-1 block w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded"', 'class="mt-1 block w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded dark:text-white"')

# 2. Vue Script Additions
# Add isDarkMode and settingsTab to data
vue_data_addition = r'''
                    currentView: 'dashboard',
                    settingsTab: 'system',
                    isDarkMode: false,
'''
html = re.sub(r"currentView: 'dashboard',", vue_data_addition, html)

# Add toggleDarkMode and mounted logic
vue_mounted_addition = r'''
            mounted() {
                // Initialize Dark Mode
                const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                this.isDarkMode = localStorage.getItem('darkMode') ? localStorage.getItem('darkMode') === 'true' : prefersDark;
                if (this.isDarkMode) {
                    document.documentElement.classList.add('dark');
                }
                
                this.fetchData();
'''
html = html.replace('            mounted() {\n                this.fetchData();', vue_mounted_addition)

vue_methods_addition = r'''
            methods: {
                toggleDarkMode() {
                    this.isDarkMode = !this.isDarkMode;
                    if (this.isDarkMode) {
                        document.documentElement.classList.add('dark');
                    } else {
                        document.documentElement.classList.remove('dark');
                    }
                    localStorage.setItem('darkMode', this.isDarkMode);
                },
'''
html = html.replace('            methods: {', vue_methods_addition)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(html)
