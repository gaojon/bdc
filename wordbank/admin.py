"""Admin configuration for wordbank with CSV import."""

import io

from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path

from wordbank.models import Word, WordBank, WordBankEntry
from wordbank.services import import_csv_to_bank


class WordBankEntryInline(admin.TabularInline):
    model = WordBankEntry
    extra = 1
    autocomplete_fields = ("word",)


@admin.register(WordBank)
class WordBankAdmin(admin.ModelAdmin):
    list_display = ("name", "word_count", "created_at")
    search_fields = ("name",)
    inlines = [WordBankEntryInline]
    change_list_template = "admin/wordbank/wordbank_change_list.html"

    @admin.display(description="Words")
    def word_count(self, obj):
        return obj.entries.count()

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv_view),
                name="wordbank-import-csv",
            ),
            path(
                "<int:bank_id>/import-csv/",
                self.admin_site.admin_view(self.import_csv_for_bank_view),
                name="wordbank-import-csv-for-bank",
            ),
        ]
        return custom_urls + urls

    def import_csv_view(self, request):
        """Import CSV into a selected word bank."""
        word_banks = WordBank.objects.all()

        if request.method == "POST":
            bank_id = request.POST.get("word_bank_id")
            csv_file = request.FILES.get("csv_file")

            if not bank_id or not csv_file:
                messages.error(request, "Please select a word bank and upload a CSV file.")
                return redirect("admin:wordbank-import-csv")

            try:
                word_bank = WordBank.objects.get(id=bank_id)
            except WordBank.DoesNotExist:
                messages.error(request, "Invalid word bank.")
                return redirect("admin:wordbank-import-csv")

            try:
                file_data = csv_file.read()
                try:
                    text = file_data.decode("utf-8")
                except UnicodeDecodeError:
                    text = file_data.decode("gbk")

                file_obj = io.StringIO(text)
                result = import_csv_to_bank(word_bank, file_obj)

                messages.success(
                    request,
                    f"Imported into '{word_bank.name}': "
                    f"{result['created']} created, {result['skipped']} skipped.",
                )

                if result["errors"]:
                    for err in result["errors"][:5]:
                        messages.warning(request, err)

            except Exception as e:
                messages.error(request, f"Import failed: {e}")

            return redirect("admin:wordbank-import-csv")

        context = {
            "word_banks": word_banks,
            "title": "Import CSV to Word Bank",
        }
        return render(request, "admin/wordbank/import_csv.html", context)

    def import_csv_for_bank_view(self, request, bank_id):
        """Import CSV directly into a specific word bank (from its change page)."""
        try:
            word_bank = WordBank.objects.get(id=bank_id)
        except WordBank.DoesNotExist:
            messages.error(request, "Word bank not found.")
            return redirect("admin:wordbank_wordbank_changelist")

        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")

            if not csv_file:
                messages.error(request, "Please upload a CSV file.")
                return redirect("admin:wordbank-import-csv-for-bank", bank_id=bank_id)

            try:
                file_data = csv_file.read()
                try:
                    text = file_data.decode("utf-8")
                except UnicodeDecodeError:
                    text = file_data.decode("gbk")

                file_obj = io.StringIO(text)
                result = import_csv_to_bank(word_bank, file_obj)

                messages.success(
                    request,
                    f"Imported into '{word_bank.name}': "
                    f"{result['created']} created, {result['skipped']} skipped.",
                )

                if result["errors"]:
                    for err in result["errors"][:5]:
                        messages.warning(request, err)

            except Exception as e:
                messages.error(request, f"Import failed: {e}")

            return redirect(
                "admin:wordbank_wordbank_change", object_id=bank_id
            )

        context = {
            "word_bank": word_bank,
            "title": f"Import CSV to: {word_bank.name}",
        }
        return render(request, "admin/wordbank/import_csv_for_bank.html", context)


@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ("word", "part_of_speech", "definition", "is_phrase")
    list_filter = ("part_of_speech", "is_phrase")
    search_fields = ("word", "definition")
