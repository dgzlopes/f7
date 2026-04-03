# f7

Thin [hledger](https://hledger.org/) wrapper for managing personal finances from the terminal.

- Get a working setup in seconds (`f7 init`)
- Multiple journal contexts (money, points, investments...)
- Built-in forecasting via periodic rules
- AI-friendly


## Requirements

- [hledger](https://hledger.org/install.html)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)

## Install

```bash
uv tool install "git+https://github.com/dgzlopes/f7"
```

## Usage

```bash
f7 init [dir]   # guided setup
f7 ctx          # switch journal context
f7 bs           # balance sheet
f7 is           # income statement
f7 bal          # balance report
f7 outflow      # expenses and liabilities with positive balance
f7 reg [acct]   # transaction register
f7 fmt          # format journal with hledger-fmt
f7 ui           # launch hledger-ui (interactive TUI)
f7 web          # launch hledger-web
```

### Flags

| Flag | Description |
|------|-------------|
| `-l` | Liquid accounts only (excludes property, vehicles, mortgages) |
| `-fm` | Forecast next 6 months |
| `-fy` | Forecast multi-year projection |
| `-p` | Show percentages (balance sheet) |

## License

MIT
