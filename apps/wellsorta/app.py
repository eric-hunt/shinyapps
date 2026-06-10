import io
import string
import zipfile

import pandas as pd
from shiny import reactive
from shiny.express import input, render, ui


def make_well_order(
    num_wells: int = 96, by: str = "column", pad: bool = False
) -> list[str]:
    assert num_wells in (96, 384), "num_wells must be 96 or 384"
    assert by in ("column", "row"), 'by must be "column" or "row"'

    if num_wells == 384:
        x, y = 24, 16
    else:
        x, y = 12, 8

    well_letters = list(string.ascii_uppercase[:y])
    well_numbers = [str(n).zfill(2) if pad else str(n) for n in range(1, x + 1)]

    if by == "row":
        letter_labels = [l for l in well_letters for _ in range(x)]
        number_labels = well_numbers * y
    else:
        letter_labels = well_letters * x
        number_labels = [n for n in well_numbers for _ in range(y)]

    return [l + n for l, n in zip(letter_labels, number_labels)]


def read_csv_first_block(path: str, skip: int = 0) -> pd.DataFrame:
    """Read only the first block of a CSV, stopping at the first blank line."""
    with open(path, "r") as f:
        lines = f.readlines()

    # Skip the header rows, then find the first blank line in the data block
    data_lines = lines[skip:]
    blank = next(
        (i for i, line in enumerate(data_lines) if line.strip() == ""),
        len(data_lines),
    )

    # nrows excludes the column header row, which read_csv handles separately
    return pd.read_csv(path, skiprows=skip, nrows=blank - 1)


results = reactive.value(None)
status = reactive.value("")

with ui.sidebar():
    ui.input_file("files", "Select CSV files", multiple=True, accept=[".csv"])
    ui.input_radio_buttons(
        "arrange_by",
        "Arrange by",
        choices={"column": "Column", "row": "Row"},
        selected="column",
    )
    ui.input_numeric("skip", "Skip rows (default 1)", value=1, min=0, step=1)
    ui.input_action_button("process", "Process", class_="btn-primary w-100")

    @render.text
    def status_text():
        return status()

    @render.download(
        label="Download .zip",
        filename="arranged_wells.zip",
    )
    def download_zip():
        res = results()
        if not res:
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, df in res.items():
                zf.writestr(f"{name}.csv", df.to_csv(index=False).encode())
        buf.seek(0)
        yield buf.read()


@reactive.effect
@reactive.event(input.process)
def _process():
    files = input.files()
    if files is None:
        return

    status.set("Processing...")

    try:
        sort_order = make_well_order(96, by=input.arrange_by())
        res = {}

        for f in files:
            file_name = f["name"].removesuffix(".csv")
            df = read_csv_first_block(f["datapath"], skip=input.skip())

            if "Well Address" not in df.columns:
                raise ValueError(
                    f'"Well Address" column not found in "{file_name}" with skip = '
                    f"{input.skip()}. Current columns: {', '.join(df.columns)}"
                )

            order_map = {well: i for i, well in enumerate(sort_order)}
            df = df.iloc[
                df["Well Address"]
                .map(lambda w: order_map.get(w, len(sort_order)))
                .argsort(kind="stable")
            ].reset_index(drop=True)

            res[file_name] = df

        results.set(res)
        status.set(f"\u2713 Processed {len(res)} file(s)")

    except Exception as e:
        status.set(f"\u2717 Error: {e}")


@render.express
def preview_tabs():
    res = results()
    if res:
        with ui.navset_card_underline():
            for name, df in res.items():
                with ui.nav_panel(name):
                    ui.HTML(
                        df.head(10).to_html(
                            index=False, classes="table table-striped table-hover"
                        )
                    )
