import csv

from django.http import HttpResponse


def build_csv_response(*, filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def format_date(value):
    return value.strftime("%Y-%m-%d") if value else ""


def format_datetime(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def format_time(value):
    return value.strftime("%H:%M") if value else ""
