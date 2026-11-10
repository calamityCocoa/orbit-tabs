/* Starts the adjacent portable Python runtime without opening a console. */
typedef unsigned short wchar_t;
__declspec(dllimport) unsigned long GetModuleFileNameW(void *, wchar_t *, unsigned long);
__declspec(dllimport) wchar_t *GetCommandLineW(void);
__declspec(dllimport) void ExitProcess(unsigned int);
__declspec(dllimport) int Py_Main(int, wchar_t **);

void mainCRTStartup(void) {
    static wchar_t executable[32768];
    static wchar_t script[32768];
    static wchar_t startup[] = L"--startup";
    static const wchar_t script_name[] = L"orbit_embedded.py";

    unsigned long length = GetModuleFileNameW(0, executable, 32768);
    if (length == 0 || length >= 32768) {
        ExitProcess(1);
        return;
    }
    unsigned long directory = length;
    while (directory && executable[directory - 1] != L'\\') {
        directory--;
    }
    if (directory + sizeof(script_name) / sizeof(script_name[0]) >= 32768) {
        ExitProcess(1);
        return;
    }
    for (unsigned long i = 0; i < directory; i++) {
        script[i] = executable[i];
    }
    for (unsigned long i = 0; i < sizeof(script_name) / sizeof(script_name[0]); i++) {
        script[directory + i] = script_name[i];
    }

    wchar_t *args[] = {executable, script, 0, 0};
    int count = 2;
    const wchar_t *command = GetCommandLineW();
    if (*command == L'"') {
        command++;
        while (*command && *command != L'"') {
            command++;
        }
        if (*command) {
            command++;
        }
    } else {
        while (*command && *command != L' ' && *command != L'\t') {
            command++;
        }
    }
    while (*command == L' ' || *command == L'\t') {
        command++;
    }
    unsigned int i = 0;
    while (startup[i] && startup[i] == command[i]) {
        i++;
    }
    if (!startup[i] && (!command[i] || command[i] == L' ')) {
        args[count++] = startup;
    }
    ExitProcess(Py_Main(count, args));
}
