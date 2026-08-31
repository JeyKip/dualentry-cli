"""Shared CLI utilities."""

import difflib

import typer

# typer >= 0.26 vendors click; TyperGroup raises the vendored UsageError.
from typer._click.exceptions import UsageError
from typer.core import TyperGroup

LOGO = r"""
 /$$$$$$$                      /$$                       /$$
| $$__  $$                    | $$                      | $$
| $$  \ $$ /$$   /$$  /$$$$$$ | $$  /$$$$$$  /$$$$$$$  /$$$$$$    /$$$$$$  /$$   /$$
| $$  | $$| $$  | $$ |____  $$| $$ /$$__  $$| $$__  $$|_  $$_/   /$$__  $$| $$  | $$
| $$  | $$| $$  | $$  /$$$$$$$| $$| $$$$$$$$| $$  \ $$  | $$    | $$  \__/| $$  | $$
| $$  | $$| $$  | $$ /$$__  $$| $$| $$_____/| $$  | $$  | $$ /$$| $$      | $$  | $$
| $$$$$$$/|  $$$$$$/|  $$$$$$$| $$|  $$$$$$$| $$  | $$  |  $$$$/| $$      |  $$$$$$$
|_______/  \______/  \_______/|__/ \_______/|__/  |__/   \___/  |__/       \____  $$
                                                                           /$$  | $$
                                                                          |  $$$$$$/
                                                                           \______/
"""


class HelpfulGroup(TyperGroup):
    """Typer group that shows help + suggestions instead of 'No such command'."""

    def format_help(self, ctx, formatter):
        if ctx.parent is None:
            typer.echo(LOGO)
        super().format_help(ctx, formatter)

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except UsageError:
            cmd_name = args[0] if args else None
            if cmd_name:
                matches = difflib.get_close_matches(cmd_name, self.list_commands(ctx), n=3, cutoff=0.4)
                if matches:
                    hint = ", ".join(f"'{m}'" for m in matches)
                    typer.echo(f"Unknown command '{cmd_name}'. Did you mean: {hint}?\n", err=True)
                else:
                    typer.echo(f"Unknown command '{cmd_name}'.\n", err=True)
            typer.echo(ctx.get_help())
            ctx.exit(2)
