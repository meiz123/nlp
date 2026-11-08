import json, sys, threading
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QLineEdit,QPlainTextEdit,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QCheckBox,QInputDialog,QSplitter,QFrame,QComboBox,QProgressBar,QHeaderView,QAbstractItemView,QScrollArea,QMenu,QTabWidget,QSizePolicy)
from PySide6.QtGui import QColor
from .core import Project,load_csv,technical,fingerprint,export_rows,export_training

from .routing import ReviewRouter, ReviewCancelled, ModelsUnavailable, model_chain, DEFAULT_FALLBACKS

from .translation_worker import TranslationWorker
from .text_input import SourceTextEdit

DEFAULT_MODEL = 'gemini-3.5-flash-lite'

class Worker(QThread):
    progress=Signal(str)
    updated=Signal(int,int)
    failed=Signal(str)
    def __init__(self,path,key,model,context,offline,fallbacks=()):
        super().__init__();self.args=(path,key,model,context,offline);self.stop=threading.Event();self.fallbacks=fallbacks
    def run(self):
        p=None;client=None
        try:
            path,key,model,context,offline=self.args;p=Project(path)
            if not offline:
                from .gemini import Gemini
                client=Gemini(key)
                router=ReviewRouter(client,p,model_chain(model,self.fallbacks),context,self.stop,self.progress.emit)
            pending=[r for r in p.rows() if not r['reviewed']]
            self.updated.emit(0,len(pending))
            for index,row in enumerate(pending):
                if self.stop.is_set():break
                if row['reviewed']:continue
                made_request=False
                issues=technical(row['english'],row['vietnamese'])
                if offline:
                    result={'status':'REVIEW','issues':issues,'reason':'Chỉ kiểm tra kỹ thuật; chưa đánh giá ngôn ngữ.','suggestion':''}
                else:
                    task='translate' if not row['vietnamese'].strip() else 'review'
                    requests_before=router.request_count
                    result=router.review(row,task=task)
                    made_request=router.request_count>requests_before
                    if task=='translate':issues=[]
                    if issues:result={**result,'status':'FAIL' if result['status']=='FAIL' or 'Placeholder không khớp' in issues or 'Thiếu bản dịch tiếng Việt' in issues else 'REVIEW','issues':issues+result['issues']}
                    if self.stop.is_set():break
                p.save_result(row['key'],result);self.progress.emit('Đã lưu: '+row['key']);self.updated.emit(index+1,len(pending))
                if made_request and index+1<len(pending) and self.stop.wait(5):break
        except ReviewCancelled:
            pass
        except ModelsUnavailable as exc:
            self.failed.emit(str(exc)+'. Đã giữ tiến độ; có thể review thủ công hoặc tiếp tục sau.')
        except Exception as exc:
            code=getattr(exc,'code',None)
            messages={'404':'Không tìm thấy model. Chọn model khác trong Cấu hình.', '429':'Đã chạm giới hạn lượt gọi. Thử lại sau hoặc kiểm tra hạn mức trong AI Studio.', '504':'Gemini phản hồi quá lâu. Thử lại sau hoặc đổi model.', '403':'Key chưa có quyền truy cập. Kiểm tra key và project trong AI Studio.', '400':'Yêu cầu không hợp lệ. Kiểm tra key, model và dữ liệu.'}
            self.failed.emit(messages.get(str(code),'Không thể kết nối Gemini. Kiểm tra mạng và thử lại.')+' Kết quả đã hoàn tất vẫn được lưu.')
        finally:
            if client:client.close()
            if p:p.close()

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Localization QA • Anh–Việt');self.resize(1380,900);self.setMinimumSize(1020,720)
        self.project=None;self.worker=None;self.data=[];self.last_error='';self.file_dialogs=[];self._selected_key=None;self._note_drafts={};self._translation_drafts={};self._draft_project=None;self._loading_feedback=False;self._manual_source='';self._manual_notes='';self._manual_result=None;self._translation_request=None
        root=QWidget();root.setObjectName('root');self.setCentralWidget(root)
        layout=QVBoxLayout(root);layout.setContentsMargins(18,14,18,12);layout.setSpacing(10)
        header=QHBoxLayout();layout.addLayout(header)
        brand=QVBoxLayout();title=QLabel('Localization QA');title.setObjectName('title');brand.addWidget(title)
        subtitle=QLabel('Không bỏ sót ý nghĩa. Giữ câu chữ tự nhiên.');subtitle.setObjectName('muted');brand.addWidget(subtitle);header.addLayout(brand);header.addStretch()
        self.project_label=QLabel('Chưa mở project');self.project_label.setObjectName('badge');header.addWidget(self.project_label)
        self.configbutton=QPushButton('Cấu hình Gemini');self.configbutton.setCheckable(True);header.addWidget(self.configbutton)
        bar=QHBoxLayout();layout.addLayout(bar);self.actions=[]
        for label,fn in [('＋ Tạo project',self.new),('Mở project / dữ liệu',self.open),('Nhập dữ liệu',self.import_csv),('Xuất báo cáo',self.export),('Xuất dữ liệu train',self.export_training_data),('Nhập bảng so sánh',self.import_comparison_csv)]:
            b=QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b);self.actions.append(b)
        bar.addStretch()
        self.settings=QFrame();self.settings.setObjectName('card');cfg=QVBoxLayout(self.settings);cfg.setContentsMargins(18,14,18,14);cfg.setSpacing(10)
        layout.addWidget(self.settings);self.configbutton.toggled.connect(self.settings.setVisible)
        line=QHBoxLayout();cfg.addLayout(line)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('Dán Gemini API key vào đây');line.addWidget(self.key,2)
        for label,fn in [('Lưu key',self.save_key),('Xóa key',self.delete_key)]:
            b=QPushButton(label);b.clicked.connect(fn);line.addWidget(b)
        line.addWidget(QLabel('Model'))
        self.model=QLineEdit(DEFAULT_MODEL);self.model.setMinimumWidth(230);line.addWidget(self.model)
        fallbackline=QHBoxLayout();fallbackline.addWidget(QLabel('Model dự phòng'))
        self.fallback_models=QLineEdit(DEFAULT_FALLBACKS);self.fallback_models.setPlaceholderText('Tên model, cách nhau bằng dấu phẩy; để trống để tắt')
        fallbackline.addWidget(self.fallback_models,1);cfg.addLayout(fallbackline)
        fallbacknote=QLabel('Tự chuyển khi hết lượt, dịch vụ lỗi hoặc kết quả không hợp lệ. Tối đa 3 model dự phòng; cùng API key và tài khoản. Hạn mức và chi phí theo từng model.');fallbacknote.setWordWrap(True);fallbacknote.setObjectName('muted');cfg.addWidget(fallbacknote)
        self.context=QPlainTextEdit();self.context.setPlaceholderText('Ngữ cảnh và thuật ngữ • Ví dụ: App gấp giấy cho người mới. unfold = mở nếp gấp. Giọng văn ngắn gọn, thân thiện.');self.context.setFixedHeight(65);cfg.addWidget(self.context)
        note=QLabel('Key lưu trong kho bảo mật của máy. Khi dùng AI, câu dịch và ngữ cảnh được gửi đến Google; hạn mức theo tài khoản.');note.setWordWrap(True);note.setObjectName('muted');cfg.addWidget(note)
        try:
            import keyring
            self.key.setText(keyring.get_password('LocalizationQA','gemini') or '')
        except Exception:pass
        self.configbutton.setChecked(not bool(self.key.text()));self.settings.setVisible(self.configbutton.isChecked())
        stats=QHBoxLayout();layout.addLayout(stats);self.stat_labels=[]
        for name in ['TỔNG SỐ CÂU','CẦN XEM LẠI','LỖI RÕ RÀNG','ĐÃ REVIEW']:
            card=QFrame();card.setObjectName('card');box=QHBoxLayout(card);box.setContentsMargins(12,8,12,8)
            number=QLabel('0');number.setObjectName('number');box.addWidget(number);label=QLabel(name);label.setObjectName('muted');box.addWidget(label);stats.addWidget(card);self.stat_labels.append(number)
        filters=QHBoxLayout();layout.addLayout(filters)
        self.search=QLineEdit();self.search.setPlaceholderText('Tìm key, câu tiếng Anh hoặc tiếng Việt…');self.search.textChanged.connect(self.filter_rows);filters.addWidget(self.search,2)
        self.filter=QComboBox();self.filter.addItems(['Tất cả','Cần xem lại','Lỗi rõ ràng','Chưa kiểm tra','Đã review','Chưa review']);self.filter.currentIndexChanged.connect(self.filter_rows);filters.addWidget(self.filter)
        self.offline=QCheckBox('Chỉ kiểm tra kỹ thuật');filters.addWidget(self.offline)
        self.runbutton=QPushButton('Bắt đầu kiểm tra');self.runbutton.setObjectName('primary');self.runbutton.clicked.connect(self.run);filters.addWidget(self.runbutton)
        self.stopbutton=QPushButton('Dừng');self.stopbutton.clicked.connect(self.stop);self.stopbutton.setEnabled(False);filters.addWidget(self.stopbutton)
        self.review_splitter=QSplitter(Qt.Orientation.Horizontal);layout.addWidget(self.review_splitter,1)
        left=QFrame();left.setObjectName('card');left.setMinimumWidth(270);leftbox=QVBoxLayout(left);leftbox.setContentsMargins(0,0,0,0)
        self.empty=QLabel('Mở project hoặc dữ liệu để bắt đầu.\n\nCó thể chọn cả hai JSON Anh–Việt.');self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setObjectName('empty');self.empty.setWordWrap(True);leftbox.addWidget(self.empty)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Key','Danh sách câu','Tiếng Việt','Đánh giá','Review','Ghi chú','Local','Gemini']);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.table.setAlternatingRowColors(True);self.table.setShowGrid(False);self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.itemSelectionChanged.connect(self.select);self.table.itemChanged.connect(self.table_feedback_changed)
        self.table.horizontalHeader().setStretchLastSection(False)
        for column in (0,2,5,6,7):self.table.setColumnHidden(column,True)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(3,95)
        self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(4,64)
        leftbox.addWidget(self.table);self.review_splitter.addWidget(left)
        self.review_panel=QFrame();self.review_panel.setObjectName('reviewCard');self.review_panel.setMinimumWidth(600)
        right=QVBoxLayout(self.review_panel);right.setContentsMargins(16,12,16,12);right.setSpacing(8)
        self.focuslabel=QLabel('CHỌN MỘT CÂU ĐỂ REVIEW');self.focuslabel.setObjectName('focusTitle');right.addWidget(self.focuslabel)
        self.rowtitle=QLabel('');self.rowtitle.setObjectName('activeKey');self.rowtitle.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);right.addWidget(self.rowtitle)
        entrybar=QHBoxLayout();self.manual_mode=QCheckBox('Nhập trực tiếp');self.manual_mode.toggled.connect(self.toggle_manual);entrybar.addWidget(self.manual_mode)
        self.pastebutton=QPushButton('Dán');self.pastebutton.setToolTip('Dán văn bản từ clipboard • Cmd+V hoặc Ctrl+V');self.pastebutton.clicked.connect(self.paste_source);entrybar.addWidget(self.pastebutton)
        self.translatebutton=QPushButton('Dịch sang tiếng Việt');self.translatebutton.clicked.connect(self.translate_source);entrybar.addWidget(self.translatebutton)
        self.save_sentence=QPushButton('Lưu câu vào project');self.save_sentence.clicked.connect(self.save_manual_sentence);entrybar.addWidget(self.save_sentence);entrybar.addStretch();right.addLayout(entrybar)
        sourcearea=QWidget();sourcearea.setMinimumHeight(125);sourcebar=QHBoxLayout(sourcearea);sourcebar.setContentsMargins(0,0,0,0);sourcebar.setSpacing(12);right.addWidget(sourcearea,3)
        for label,fieldname in [('TIẾNG ANH','source'),('BẢN DỊCH HIỆN TẠI','current')]:
            box=QVBoxLayout();box.setSpacing(5);box.addWidget(QLabel(label))
            field=SourceTextEdit() if fieldname=='source' else QPlainTextEdit();field.setReadOnly(True);field.setMinimumHeight(58);field.setMaximumHeight(130);setattr(self,fieldname,field);box.addWidget(field,1)
            if fieldname=='source':
                self.translatebelow=QPushButton('Dịch bằng model');self.translatebelow.setObjectName('primary');self.translatebelow.clicked.connect(self.translate_source);box.addWidget(self.translatebelow)
            sourcebar.addLayout(box)
        self.source.setPlaceholderText('Nhập hoặc dán câu tiếng Anh tại đây, rồi bấm Dịch sang tiếng Việt');self.source.textChanged.connect(self.source_edited)
        self.reviewtabs=QTabWidget();self.reviewtabs.setObjectName('reviewTabs');self.reviewtabs.setMinimumHeight(100);right.addWidget(self.reviewtabs,3)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMinimumHeight(50);self.reviewtabs.addTab(self.detail,'Nhận xét & ngữ cảnh')
        comparison=QWidget();comparebox=QHBoxLayout(comparison);comparebox.setContentsMargins(8,6,8,6);comparebox.setSpacing(12)
        for title,fieldname in [('LOCAL','local_text'),('GEMINI','gemini_text')]:
            box=QVBoxLayout();box.setSpacing(5);box.addWidget(QLabel(title));field=QPlainTextEdit();field.setReadOnly(True);field.setMinimumHeight(50);setattr(self,fieldname,field);box.addWidget(field,1);comparebox.addLayout(box)
        self.reviewtabs.addTab(comparison,'So sánh Local · Gemini')
        revision=QWidget();revisionbox=QHBoxLayout(revision)
        for label,name in [('TRƯỚC KHI SỬA','before_revision'),('SAU KHI SỬA','after_revision')]:
            column=QVBoxLayout();column.addWidget(QLabel(label));field=QPlainTextEdit();field.setReadOnly(True);setattr(self,name,field);column.addWidget(field);revisionbox.addLayout(column)
        self.reviewtabs.addTab(revision,'Trước và sau chỉnh sửa')
        editbar=QHBoxLayout();editbar.setSpacing(12);right.addLayout(editbar,3)
        finalbox=QVBoxLayout();finalbox.setSpacing(5);final_label=QLabel('BẢN SỬA CUỐI');final_label.setToolTip('Chỉ dùng để train sau khi bạn duyệt bản sửa.');finalbox.addWidget(final_label)
        self.translation=QPlainTextEdit();self.translation.setMinimumHeight(70);self.translation.textChanged.connect(self.translation_edited);self.translation.setPlaceholderText('Chỉnh bản dịch tại đây rồi duyệt');finalbox.addWidget(self.translation,1);editbar.addLayout(finalbox,3)
        notesbox=QVBoxLayout();notesbox.setSpacing(5);noteshead=QHBoxLayout();noteshead.addWidget(QLabel('GHI CHÚ'));noteshead.addStretch()
        self.revisebutton=QPushButton('Sửa lại theo ghi chú');self.revisebutton.setObjectName('compact');self.revisebutton.setToolTip('Gửi câu Anh, bản dịch đang sửa và ghi chú đến Gemini để tạo bản sửa mới');self.revisebutton.clicked.connect(self.revise_source);noteshead.addWidget(self.revisebutton)
        self.savenotes=QPushButton('Lưu');self.savenotes.setToolTip('Lưu ghi chú, không duyệt bản dịch.');self.savenotes.setObjectName('compact');self.savenotes.clicked.connect(self.save_review_notes);noteshead.addWidget(self.savenotes);notesbox.addLayout(noteshead)
        self.notes=QPlainTextEdit();self.notes.setMinimumHeight(70);self.notes.setPlaceholderText('Gợi ý chưa tốt ở đâu?');self.notes.textChanged.connect(self.note_edited);notesbox.addWidget(self.notes,1);editbar.addLayout(notesbox,2)
        finalactions=QHBoxLayout();right.addLayout(finalactions)
        self.reviewcheck=QCheckBox('Đã review');self.reviewcheck.setToolTip('Đã xem câu; bản sửa phải được duyệt riêng để train.');self.reviewcheck.toggled.connect(self.review_toggled);finalactions.addWidget(self.reviewcheck);finalactions.addStretch()
        self.approvebutton=QPushButton('✓ Duyệt bản sửa');self.approvebutton.setObjectName('primary');self.approvebutton.clicked.connect(self.approve);finalactions.addWidget(self.approvebutton)
        self.nextbutton=QPushButton('Câu tiếp →');self.nextbutton.setToolTip('Chuyển đến câu tiếp theo chưa review');self.nextbutton.clicked.connect(self.next_row);finalactions.addWidget(self.nextbutton)
        self.review_splitter.addWidget(self.review_panel);self.review_splitter.setStretchFactor(0,1);self.review_splitter.setStretchFactor(1,3);self.review_splitter.setSizes([330,970])
        footer=QHBoxLayout();layout.addLayout(footer);self.status=QLabel('Sẵn sàng • Tạo hoặc mở project để bắt đầu.');self.status.setWordWrap(True);footer.addWidget(self.status,1)
        self.progressbar=QProgressBar();self.progressbar.setRange(0,1);self.progressbar.setValue(0);self.progressbar.setFixedWidth(220);self.progressbar.setFormat('%v / %m câu');footer.addWidget(self.progressbar)
        self.setStyleSheet(STYLE)
        self.manual_mode.setChecked(True)
        self.refresh_controls()
    def refresh_controls(self):
        has=bool(self.project);running=bool(self.worker)
        for w in self.actions:w.setEnabled(not running)
        self.runbutton.setEnabled(not running and (has or self.manual_mode.isChecked()))
        manual=self.manual_mode.isChecked()
        self.pastebutton.setEnabled(manual and not running)
        self.source.setReadOnly(running or not manual);self.manual_mode.setEnabled(not running)
        self.translatebutton.setEnabled(not running and (manual or bool(self._selected_key)))
        self.translatebelow.setEnabled(self.translatebutton.isEnabled())
        self.translatebelow.setText('Đang dịch…' if running else 'Dịch bằng model')
        self.save_sentence.setVisible(manual);self.save_sentence.setEnabled(manual and not running and self._manual_result is not None)
        selected=not manual and 0<=self.table.currentRow()<len(self.data)
        self.approvebutton.setEnabled(selected and not running);self.translation.setReadOnly(running or not (selected or manual));self.nextbutton.setEnabled(selected and not running)
        self.revisebutton.setEnabled(not running and (selected or manual))
        self.notes.setReadOnly(running or not (selected or manual));self.reviewcheck.setEnabled(selected and not running);self.savenotes.setEnabled((selected or manual) and not running)
        self.savenotes.setText('Lưu nháp' if manual else 'Lưu')
        self.savenotes.setToolTip('Ghi chú đi cùng câu nhập trực tiếp; lưu câu vào project để giữ feedback lâu dài.' if manual else 'Lưu ghi chú, không duyệt bản dịch.')
    def filter_rows(self):
        query=self.search.text().casefold();mode=self.filter.currentIndex()
        for i,r in enumerate(self.data):
            result=json.loads(r['result']) if r['result'] else {};status=result.get('status','')
            comparison=self.project.backend_results(r['key']).get('comparison',{}) if mode==1 else {}
            needsreview=status=='REVIEW' or (bool(comparison) and comparison.get('winner')!='tie' and not r['reviewed'])
            match=[True,needsreview,status=='FAIL',not r['result'],bool(r['reviewed']),not r['reviewed']][mode]
            self.table.setRowHidden(i,not (match and query in ' '.join([r['key'],r['english'],r['vietnamese']]).casefold()))
        i=self.table.currentRow()
        if i<0 or self.table.isRowHidden(i):
            self.table.clearSelection();self.table.setCurrentCell(-1,-1)
            for index in range(len(self.data)):
                if not self.table.isRowHidden(index):self.table.selectRow(index);break
        self.select()
    def next_row(self):
        current=self.table.currentRow()
        for i in list(range(current+1,len(self.data)))+list(range(0,current+1)):
            if not self.table.isRowHidden(i) and not self.data[i]['reviewed']:
                self.table.selectRow(i);self.table.scrollToItem(self.table.item(i,1),QAbstractItemView.ScrollHint.PositionAtCenter);return
        self.status.setText('Không còn câu chưa review trong bộ lọc hiện tại.')
    def on_progress(self,done,total):
        self.progressbar.setRange(0,max(1,total));self.progressbar.setValue(done)
        self.refresh()
    def error(self,e):QMessageBox.warning(self,'Thông báo',str(e))
    def attach(self,path):
        try:
            if self.manual_mode.isChecked():self.manual_mode.setChecked(False)
            p=Project(path)
            if self.project:
                self._flush_note_drafts()
                self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text());self.project.set_setting('fallback_models',self.fallback_models.text());self.project.close()
            self._selected_key=None;self._note_drafts.clear()
            self.project=p
            try:manual_draft=json.loads(p.setting('manual_entry_draft','{}'))
            except (ValueError,TypeError):manual_draft={}
            if not isinstance(manual_draft,dict):manual_draft={}
            self._manual_source=manual_draft.get('english','') if isinstance(manual_draft.get('english',''),str) else ''
            self._manual_notes=manual_draft.get('notes','') if isinstance(manual_draft.get('notes',''),str) else ''
            self.context.setPlainText(p.setting('context'));self.model.setText(p.setting('model',DEFAULT_MODEL));self.fallback_models.setText(p.setting('fallback_models',DEFAULT_FALLBACKS));self.project_label.setText(__import__('pathlib').Path(path).name);self.project_label.setToolTip(path);self.refresh();self.status.setText('Project đã mở • '+path);return True
        except Exception as e:self.error(e);return False
    def choose_file(self,title,filters,save=False):
        dialog=QFileDialog(self,title);dialog.setNameFilters(filters.split(';;'))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        # Avoid Qt's filename-completer popup and changing table columns while
        # macOS accessibility clients are enumerating the file dialog.
        dialog.setViewMode(QFileDialog.ViewMode.List)
        filename=dialog.findChild(QLineEdit,'fileNameEdit')
        if filename is not None:filename.setCompleter(None)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
        if not save:dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        # Keep dialog objects alive: macOS accessibility may still reference the closed dialog.
        self.file_dialogs.append(dialog)
        if dialog.exec():return dialog.selectedFiles()[0],dialog.selectedNameFilter()
        return '', ''
    def choose_files(self,title,filters):
        """Select a single paired document or two separate JSON language files."""
        dialog=QFileDialog(self,title);dialog.setNameFilters(filters.split(';;'))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setViewMode(QFileDialog.ViewMode.List)
        filename=dialog.findChild(QLineEdit,'fileNameEdit')
        if filename is not None:filename.setCompleter(None)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.file_dialogs.append(dialog)
        return dialog.selectedFiles() if dialog.exec() else []
    def new(self):
        path,_=self.choose_file('Tạo project','Project (*.lqa)',True)
        if path:self.attach(path if path.endswith('.lqa') else path+'.lqa')
    def open(self):
        if self.worker:return self.error('Dừng kiểm tra trước khi mở dữ liệu khác')
        paths=self.choose_files('Mở project hoặc dữ liệu Anh–Việt',
            'Project và dữ liệu (*.lqa *.csv *.json *.xlsx *.xls *.docx *.doc);;Project (*.lqa);;JSON (*.json);;CSV (*.csv);;Excel (*.xlsx *.xls);;Word (*.docx *.doc)')
        if not paths:return
        try:
            from pathlib import Path
            projects=[path for path in paths if Path(path).suffix.lower()=='.lqa']
            if projects:
                if len(paths)!=1:raise ValueError('Chọn một project .lqa riêng; không chọn chung với dữ liệu đầu vào.')
                self.attach(projects[0])
            else:self.import_selected_paths(paths,create_project=True)
        except Exception as e:self.error(e)
    def create_input_project(self):
        from pathlib import Path
        path,_=self.choose_file('Lưu project để giữ tiến độ review','Project (*.lqa)',True)
        if not path:return False
        if not path.lower().endswith('.lqa'):path+='.lqa'
        if Path(path).exists():raise ValueError('Chọn tên project mới để giữ nguyên dữ liệu trong project đã có.')
        return self.attach(path)

    def confirm_input_report(self, rows, report):
        diagnostics=report.get('diagnostics',[]) if isinstance(report,dict) else []
        if not diagnostics:return True
        examples='\n'.join('• '+str(d.get('key',''))+': '+str(d.get('message',d.get('code',''))) for d in diagnostics[:3])
        message=(f'Dữ liệu có {len(diagnostics)} cảnh báo về cặp câu hoặc cấu trúc. '
                 f'Có {len(rows)} dòng để nhập. Các ô ngôn ngữ bị thiếu sẽ giữ trống để bạn kiểm tra.\n\n'
                 +examples+'\n\n'
                 'Chỉ tiếp tục nếu bạn đã xác nhận đây là đúng hai nguồn ngôn ngữ. Nhập dữ liệu chưa đánh dấu review hay duyệt bản sửa.')
        return QMessageBox.question(self,'Kiểm tra dữ liệu trước khi nhập',message,
                                   QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
    def apply_input_rows(self, rows, report=None, *, confirmed=False):
        if not rows:raise ValueError('File chưa có cặp câu nào để nhập')
        if not confirmed and not self.confirm_input_report(rows, report or {}):
            self.status.setText('Đã hủy nhập dữ liệu. Project hiện tại được giữ nguyên.');return False
        # Parsing and warning confirmation finish before any project/feedback write.
        self._flush_note_drafts();self.project.import_rows(rows);self._note_drafts.clear();self.refresh()
        count=len((report or {}).get('diagnostics',[]))
        self.status.setText(f'Đã nhập {len(rows)} cặp câu'+(f' • {count} cảnh báo dữ liệu' if count else '')+'. Chưa tự duyệt bản sửa nào.')
        return True
    def choose_json_roles(self, paths):
        """Resolve filename roles, or ask explicitly when names are ambiguous."""
        from pathlib import Path
        from .input_json import resolve_json_pair, AmbiguousJSONPairError
        try:return resolve_json_pair(paths)
        except AmbiguousJSONPairError:
            choices=[str(Path(path)) for path in paths]
            selected,accepted=QInputDialog.getItem(self,'Chọn file nguồn tiếng Anh',
                'Tên file chưa chỉ rõ ngôn ngữ. Chọn file tiếng Anh; file còn lại sẽ là tiếng Việt:',
                choices,0,False)
            if not accepted:return None
            index=choices.index(selected)
            return Path(paths[index]),Path(paths[1-index])
    def import_selected_paths(self, paths, *, create_project=False):
        """Finish parsing and role selection before any project write."""
        from pathlib import Path
        from .input_json import load_json,load_json_pair,SingleLanguageJSONError
        if not paths:return False
        if len(paths)>2:raise ValueError('Chọn một file CSV/Excel/Word/JSON song ngữ hoặc đúng hai file JSON Anh–Việt.')
        paths=[Path(path) for path in paths];report={}
        if len(paths)==2:
            if any(path.suffix.lower()!='.json' for path in paths):
                raise ValueError('Chỉ chọn nhiều file khi nhập hai JSON Anh–Việt. CSV, Excel và Word cần chọn từng file.')
            roles=self.choose_json_roles(paths)
            if roles is None:
                self.status.setText('Đã hủy chọn ngôn ngữ. Project hiện tại được giữ nguyên.');return False
            rows,report=load_json_pair(*roles);sources=list(roles)
        else:
            path=paths[0];suffix=path.suffix.lower();sources=[path]
            if suffix=='.csv':rows=load_csv(path)
            elif suffix=='.json':
                try:rows,report=load_json(path)
                except SingleLanguageJSONError:
                    counterpart,_=self.choose_file('JSON này chứa một ngôn ngữ • Chọn file JSON ngôn ngữ còn lại','JSON (*.json)')
                    if not counterpart:
                        self.status.setText('Đã hủy nhập cặp JSON. Chọn cả file Anh và Việt để nhập.');return False
                    roles=self.choose_json_roles([path,Path(counterpart)])
                    if roles is None:
                        self.status.setText('Đã hủy chọn ngôn ngữ. Project hiện tại được giữ nguyên.');return False
                    rows,report=load_json_pair(*roles);sources=list(roles)
            elif suffix in ('.xlsx','.xls'):
                from .input_excel import load_excel
                rows=load_excel(path)
            elif suffix in ('.docx','.doc'):
                from .input_word import load_word
                rows=load_word(str(path))
            else:raise ValueError('Chọn CSV, Excel XLSX, JSON, DOCX hoặc DOC. Có thể chọn cùng lúc hai JSON Anh–Việt.')
        from .preprocess import preprocess_rows
        rows,preprocessing=preprocess_rows(rows)
        report={**report,'preprocessing':report.get('preprocessing',preprocessing)}
        report['diagnostics']=report.get('diagnostics',[])+preprocessing['diagnostics']
        if not rows:raise ValueError('File chưa có cặp câu nào để nhập')
        if create_project:
            if not self.confirm_input_report(rows,report):return False
            if not self.create_input_project():
                self.status.setText('Đã hủy lưu project. Dữ liệu chưa được nhập.');return False
        imported=self.apply_input_rows(rows,report,confirmed=create_project)
        if imported:
            self.status.setText(self.status.text()+' Nguồn: '+' + '.join(path.name for path in sources))
            self.status.setToolTip('\n'.join(str(path) for path in sources))
        return imported
    def import_csv(self):
        """Retain the callback name; the primary input now accepts one or two files."""
        if self.worker:return self.error('Dừng kiểm tra trước khi nhập dữ liệu')
        paths=self.choose_files('Chọn dữ liệu • Có thể chọn cùng lúc hai JSON Anh–Việt',
            'Dữ liệu (*.csv *.json *.xlsx *.xls *.docx *.doc);;JSON Anh–Việt (*.json);;CSV (*.csv);;Excel (*.xlsx *.xls);;Word (*.docx *.doc)')
        if not paths:return
        try:self.import_selected_paths(paths,create_project=not bool(self.project))
        except Exception as e:self.error(e)
    def import_json_pair(self):
        if not self.project or self.worker:return self.error('Tạo hoặc mở project trước; dừng kiểm tra nếu đang chạy')
        english,_=self.choose_file('Chọn JSON nguồn tiếng Anh','JSON (*.json)')
        if not english:return
        vietnamese,_=self.choose_file('Chọn JSON bản dịch tiếng Việt','JSON (*.json)')
        if not vietnamese:return
        try:
            if __import__('pathlib').Path(english).resolve()==__import__('pathlib').Path(vietnamese).resolve():
                raise ValueError('Cần chọn hai file riêng: nguồn tiếng Anh và bản dịch tiếng Việt')
            from .input_json import load_json_pair
            rows,report=load_json_pair(english,vietnamese)
            self.apply_input_rows(rows,report)
        except Exception as e:self.error(e)
    def import_comparison_csv(self):
        if self.worker:return self.error('Dừng kiểm tra trước khi nhập bảng so sánh')
        path,_=self.choose_file('Nhập bảng so sánh Local–Gemini','CSV (*.csv)')
        if path:
            try:
                from .comparison import import_comparison,load_comparison_csv
                load_comparison_csv(path)
                if not self.project and not self.create_input_project():return
                self._flush_note_drafts();count=import_comparison(self.project,path);self._note_drafts.clear();self.refresh();self.status.setText(f'Đã nhập {count} câu so sánh. Chưa tự duyệt bản sửa nào.')
            except Exception as e:self.error(e)
    def refresh(self):
        if not self.project:return
        if self._draft_project is not self.project:
            self._draft_project=self.project
            try:self._translation_drafts=json.loads(self.project.setting('translation_drafts','{}'))
            except (ValueError,TypeError):self._translation_drafts={}
        oldkey=self.data[self.table.currentRow()]['key'] if 0<=self.table.currentRow()<len(self.data) else None
        self.data=self.project.rows();self.table.blockSignals(True)
        if self.table.rowCount()!=len(self.data):self.table.setRowCount(len(self.data))
        counts=[len(self.data),0,0,0];incomplete_comparison_qa=False
        for i,r in enumerate(self.data):
            result=json.loads(r['result']) if r['result'] else {};status=result.get('status','')
            counts[2]+=status=='FAIL';counts[3]+=bool(r['reviewed'])
            backend=self.project.backend_results(r['key']);comparison=backend.get('comparison',{})
            counts[1]+=status=='REVIEW' or (bool(comparison) and comparison.get('winner')!='tie' and not r['reviewed'])
            incomplete_comparison_qa|=bool(comparison) and not r['result']
            label={'PASS':'Ổn','REVIEW':'Cần xem lại','FAIL':'Có lỗi'}.get(status,{'gemini':'Gemini tốt hơn','local':'Local tốt hơn','tie':'Ngang nhau'}.get(comparison.get('winner'),'Chưa kiểm tra'))
            for j,v in enumerate([r['key'],r['english'],r['vietnamese'],label,'',r.get('notes',''),backend.get('local',{}).get('translation',''),backend.get('gemini',{}).get('translation','')]):
                item=self.table.item(i,j)
                if item is None:
                    item=QTableWidgetItem();self.table.setItem(i,j,item)
                item.setText(v);item.setToolTip(v)
                if j==4:
                    flags=Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable
                    if not self.worker:flags|=Qt.ItemFlag.ItemIsUserCheckable
                    item.setFlags(flags);item.setCheckState(Qt.CheckState.Checked if r['reviewed'] else Qt.CheckState.Unchecked)
                else:item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable)
                if j==3:item.setForeground(QColor({'PASS':'#15803d','REVIEW':'#b45309','FAIL':'#dc2626'}.get(status,'#64748b')))
        self.table.setColumnWidth(3,95);self.table.setColumnWidth(4,64)
        self.table.blockSignals(False)
        for label,value in zip(self.stat_labels,counts):label.setText(str(value))
        self.stat_labels[2].setText('—' if incomplete_comparison_qa else str(counts[2]))
        self.stat_labels[2].setToolTip('Chưa có đánh giá QA riêng cho mọi câu so sánh.' if incomplete_comparison_qa else '')
        self.empty.setVisible(not self.data)
        if oldkey:
            for i,r in enumerate(self.data):
                if r['key']==oldkey:self.table.selectRow(i);break
        self.filter_rows();self.refresh_controls()
    def select(self):
        if self.manual_mode.isChecked():return
        i=self.table.currentRow()
        if i<0 or i>=len(self.data):
            self.rowtitle.setText('');self.focuslabel.setText('CHỌN MỘT CÂU ĐỂ REVIEW')
            self._selected_key=None;self._loading_feedback=True
            for field in [self.source,self.current,self.detail,self.translation,self.notes,self.local_text,self.gemini_text,self.before_revision,self.after_revision]:field.clear()
            self.reviewcheck.setChecked(False);self._loading_feedback=False
            self.refresh_controls();return
        r=self.data[i];result=json.loads(r['result']) if r['result'] else {}
        self._selected_key=r['key'];self._loading_feedback=True
        self.notes.setPlainText(self._note_drafts.get(r['key'],r.get('notes','')));self.reviewcheck.setChecked(bool(r['reviewed']));self._loading_feedback=False
        self.rowtitle.setText(r['key']);self.rowtitle.setToolTip(r['key']);self.source.setPlainText(r['english']);self.current.setPlainText(r['vietnamese'])
        state='Đã review' if r['reviewed'] else 'Chưa review'
        self.focuslabel.setText(f'ĐANG REVIEW · Câu {i+1} / {len(self.data)} · {state}')
        self.table.scrollToItem(self.table.item(i,1),QAbstractItemView.ScrollHint.PositionAtCenter)
        backend=self.project.backend_results(r['key']);comparison=backend.get('comparison',{})
        self.local_text.setPlainText(backend.get('local',{}).get('translation','Chưa có kết quả local.'))
        self.gemini_text.setPlainText(backend.get('gemini',{}).get('translation',result.get('suggestion') or 'Chưa có bản sửa Gemini riêng.'))
        revision_history=backend.get('gemini',{}).get('revisions',result.get('revisions',[]))
        self.show_revision(revision_history)
        message='\n'.join('• '+issue for issue in result.get('issues',[]))
        if comparison:
            message+='\nSo sánh: '+comparison.get('reason','')+'\nCần thêm ngữ cảnh: '+comparison.get('context_needed','')
        provenance=('Model xử lý: '+result['model_used']+(' (dự phòng)' if result.get('used_fallback') else '')+'\n') if result.get('model_used') else ''
        self.detail.setPlainText(provenance+message+'\n'+result.get('reason','Chưa có đánh giá QA riêng; đang xem kết quả so sánh.' if comparison else 'Chưa kiểm tra. Bạn có thể tự review hoặc bắt đầu kiểm tra AI.')+'\n\nNgữ cảnh: '+(r['context'] or 'Chưa cung cấp'))
        self._loading_feedback=True
        draft=self._translation_drafts.get(r['key'],{})
        valid_draft=isinstance(draft,dict) and all(draft.get(name)==(r.get(name) or '') for name in ('english','vietnamese','context'))
        if draft and not valid_draft:
            self._translation_drafts.pop(r['key'],None);self.project.set_setting('translation_drafts',json.dumps(self._translation_drafts,ensure_ascii=False))
        self.translation.setPlainText(draft['text'] if valid_draft else r['approved'] if r['approved'] is not None else result.get('suggestion') or r['vietnamese'])
        self._loading_feedback=False;self.refresh_controls()
    def toggle_manual(self,checked):
        if self.worker:return
        self._loading_feedback=True
        if checked:
            self._flush_note_drafts();self.source.setPlainText(self._manual_source)
            self.current.clear();self.translation.clear();self.notes.setPlainText(self._manual_notes);self.detail.setPlainText('Nhập tiếng Anh và bấm Dịch sang tiếng Việt. Bản dịch mới cần bạn duyệt.')
            self.local_text.clear();self.gemini_text.clear();self.show_revision([]);self._manual_result=None
            self.focuslabel.setText('DỊCH CÂU NHẬP TRỰC TIẾP');self.rowtitle.setText('Chưa lưu vào project');self.reviewcheck.setChecked(False)
        else:
            self._manual_source=self.source.toPlainText();self._manual_notes=self.notes.toPlainText();self._manual_result=None
            self._save_manual_note_draft()
        self._loading_feedback=False
        if not checked:
            if self.project:self.refresh()
            else:self.select()
        self.refresh_controls()
        if checked:self.source.setFocus()

    def paste_source(self):
        if self.worker or not self.manual_mode.isChecked():return
        self.source.setFocus();self.source.paste()

    def source_edited(self):
        if self._loading_feedback or not self.manual_mode.isChecked():return
        self._manual_source=self.source.toPlainText();self._manual_result=None
        self.current.clear();self.translation.clear();self.show_revision([]);self.refresh_controls()

    def revise_source(self):
        self.start_translation('revise')

    def translate_source(self):
        self.start_translation('translate')

    def start_translation(self,task):
        if self.worker:return
        english=self.source.toPlainText()
        if not english.strip():return self.error('Nhập câu tiếng Anh trước khi dịch')
        if not self.key.text().strip():
            self.configbutton.setChecked(True);self.key.setFocus()
            return self.error('Nhập API key trong Cấu hình Gemini để dịch')
        try:model_chain(self.model.text(),self.fallback_models.text())
        except ValueError as exc:return self.error(exc)
        manual=self.manual_mode.isChecked()
        row={'key':'direct','english':english,'vietnamese':'','context':''}
        if not manual:
            row=next((dict(r) for r in self.data if r['key']==self._selected_key),None)
            if row is None:return self.error('Chọn câu hoặc bật Nhập trực tiếp')
        if task=='revise':
            if not self.notes.toPlainText().strip():return self.error('Nhập ghi chú về điểm cần sửa trước')
            if not self.translation.toPlainText().strip():return self.error('Cần có bản dịch hiện tại để sửa theo ghi chú')
            row={**row,'vietnamese':self.translation.toPlainText(),'revision_notes':self.notes.toPlainText()}
            previous=self._manual_result or {} if manual else self.project.backend_results(row['key']).get('gemini',{})
            row['_revision_history']=previous.get('revisions',[])
        self._translation_request=(manual,row)
        self._translation_received=False
        self.last_error='';self.worker=TranslationWorker(self.project.path if self.project else None,row,self.key.text().strip(),self.model.text().strip(),self.fallback_models.text(),self.context.toPlainText(),task=task)
        self.worker.progress.connect(self.status.setText);self.worker.failed.connect(self.run_error);self.worker.ready.connect(self.translation_ready);self.worker.finished.connect(self.translation_finished)
        self.busy(True);self.status.setText('Đang sửa theo ghi chú…' if task=='revise' else 'Đang dịch sang tiếng Việt…');self.worker.start()

    def translation_ready(self,result):
        self._translation_received=True
        manual,row=self._translation_request
        if result.get('task')=='revise':
            result={**result,'revisions':row.get('_revision_history',[])+[{'before':row['vietnamese'],'after':result['suggestion'],'notes':row['revision_notes'],'model_used':result['model_used'],'reason':result['reason']}]}
            self.show_revision(result['revisions']);self.reviewtabs.setCurrentIndex(2)
        self._loading_feedback=True
        self.translation.setPlainText(result['suggestion']);self.gemini_text.setPlainText(result['suggestion'])
        self.detail.setPlainText('Model xử lý: '+result['model_used']+(' (dự phòng)' if result.get('used_fallback') else '')+'\n'+result['reason']+'\nBản dịch mới chưa được duyệt.')
        if manual:
            self.current.setPlainText(row['vietnamese'] if result.get('task')=='revise' else result['suggestion']);self._manual_result=result
        else:
            self.project.save_backend_result(row['key'],'gemini',{**result,'translation':result['suggestion']})
            original=next((item for item in self.data if item['key']==row['key']),row)
            self._translation_drafts[row['key']]={name:original.get(name) or '' for name in ('english','vietnamese','context')}
            self._translation_drafts[row['key']]['text']=result['suggestion']
            self.project.set_setting('translation_drafts',json.dumps(self._translation_drafts,ensure_ascii=False))
        self._loading_feedback=False

    def show_revision(self,history):
        last=history[-1] if history else {}
        self.before_revision.setPlainText(last.get('before',''));self.after_revision.setPlainText(last.get('after',''))

    def translation_finished(self):
        stopped=bool(self.worker and self.worker.stop.is_set());received=getattr(self,'_translation_received',False)
        self.worker=None;self.busy(False);self.refresh_controls()
        if self.last_error:self.status.setText(self.last_error);return
        if stopped or not received:
            self.status.setText('Đã dừng dịch. Nội dung và ghi chú được giữ nguyên; bấm Dịch bằng model để thử lại.' if stopped else 'Chưa có bản dịch mới. Nội dung và ghi chú được giữ nguyên.');return
        self.status.setText(('Đã có bản dịch. Chỉnh và lưu câu vào project để review.' if self.manual_mode.isChecked() else 'Đã có bản dịch nháp. Kiểm tra trước khi duyệt.'))

    def save_manual_sentence(self):
        if self.worker or not self.manual_mode.isChecked() or not self._manual_result:return
        text=self.translation.toPlainText();english=self.source.toPlainText()
        if not text.strip() or 'Placeholder không khớp' in technical(english,text):return self.error('Bản dịch cần có nội dung và giữ đúng placeholder')
        result=dict(self._manual_result);result['suggestion']=text
        manual_notes=self.notes.toPlainText();manual_context=self.context.toPlainText()
        # Ask for a project destination only when the user explicitly saves.
        if not self.project:
            if not self.create_input_project():return
        import uuid
        key='manual/'+uuid.uuid4().hex
        self.project.import_rows([{'key':key,'english':english,'vietnamese':'','context':manual_context}])
        self.project.save_result(key,result);self.project.save_notes(key,manual_notes)
        self.manual_mode.setChecked(False)
        self._manual_notes='';self.project.set_setting('manual_entry_draft','{}')
        self.refresh();self.search.clear();self.filter.setCurrentIndex(0)
        for i,r in enumerate(self.data):
            if r['key']==key:self.table.selectRow(i);break
        self.status.setText('Đã lưu câu và bản dịch đề xuất. Chưa duyệt bản sửa.')

    def translation_edited(self):
        if self.manual_mode.isChecked():return
        if not self._loading_feedback and self._selected_key and self.project and not self.worker:
            row=next((row for row in self.data if row['key']==self._selected_key),None)
            if row is None:return
            self._translation_drafts[self._selected_key]={name:row.get(name) or '' for name in ('english','vietnamese','context')}
            self._translation_drafts[self._selected_key]['text']=self.translation.toPlainText()
            self.project.set_setting('translation_drafts',json.dumps(self._translation_drafts,ensure_ascii=False))
    def note_edited(self):
        if self._loading_feedback or self.worker:return
        if self.manual_mode.isChecked():
            self._manual_notes=self.notes.toPlainText()
        elif self._selected_key:
            self._note_drafts[self._selected_key]=self.notes.toPlainText()
    def _save_manual_note_draft(self):
        if self.project:
            self.project.set_setting('manual_entry_draft',json.dumps(
                {'english':self._manual_source,'notes':self._manual_notes},ensure_ascii=False))
    def _flush_note_drafts(self):
        if self.project:
            for key,note in self._note_drafts.items():self.project.save_notes(key,note)
        self._note_drafts.clear()
    def save_review_notes(self):
        if self.worker:return
        if self.manual_mode.isChecked():
            self._manual_source=self.source.toPlainText();self._manual_notes=self.notes.toPlainText()
            self._save_manual_note_draft()
            self.status.setText('Đã lưu nháp ghi chú trong project. Chưa duyệt bản dịch.' if self.project else 'Đã giữ nháp ghi chú trong phiên này. Lưu câu vào project để giữ lâu dài.')
            return
        if not self.project or not self._selected_key:return
        self.project.save_notes(self._selected_key,self.notes.toPlainText())
        self._note_drafts.pop(self._selected_key,None);self.refresh();self.status.setText('Đã lưu ghi chú. Bản dịch chưa tự được duyệt để train.')
    def review_toggled(self,checked):
        if self._loading_feedback or not self.project or not self._selected_key or self.worker:return
        self.project.set_reviewed(self._selected_key,checked);self.refresh();self.status.setText('Đã cập nhật trạng thái review; bản sửa được duyệt riêng.')
    def table_feedback_changed(self,item):
        if item.column()!=4 or not self.project or self.worker:return
        index=item.row()
        if not 0<=index<len(self.data):return
        self.project.set_reviewed(self.data[index]['key'],item.checkState()==Qt.CheckState.Checked)
        self.refresh();self.status.setText('Đã cập nhật trạng thái review.')
    def approve(self):
        i=self.table.currentRow()
        if self.project and 0<=i<len(self.data):
            text=self.translation.toPlainText()
            if not text.strip():return self.error('Bản dịch duyệt không được trống')
            issues=technical(self.data[i]['english'],text)
            if any(x in issues for x in ['Placeholder không khớp','Thiếu bản dịch tiếng Việt']):return self.error('Chưa thể duyệt: '+', '.join(issues))
            self.project.save_notes(self.data[i]['key'],self.notes.toPlainText());self._note_drafts.pop(self.data[i]['key'],None)
            key=self.data[i]['key'];self.project.approve(key,text)
            self._translation_drafts.pop(key,None);self.project.set_setting('translation_drafts',json.dumps(self._translation_drafts,ensure_ascii=False))
            self.refresh();self.status.setText('Đã lưu bản dịch được duyệt.')
            # Filtering can already select the next visible sentence. Advance only
            # while the just-approved sentence remains the active one.
            if self._selected_key==key:self.next_row()
    def save_key(self):
        try:
            import keyring
            keyring.set_password('LocalizationQA','gemini',self.key.text().strip());self.status.setText('Đã lưu key trong kho bảo mật của máy')
        except Exception:self.error('Không truy cập được kho bảo mật. Bạn vẫn có thể nhập key cho phiên này.')
    def delete_key(self):
        try:
            import keyring
            if keyring.get_password('LocalizationQA','gemini'):keyring.delete_password('LocalizationQA','gemini')
            self.key.clear()
        except Exception:self.error('Không xóa được key trong kho bảo mật')
    def busy(self,on):
        self.table.setEnabled(not on)
        for w in self.actions+[self.runbutton,self.approvebutton,self.context,self.model,self.fallback_models,self.offline,self.manual_mode,self.pastebutton,self.translatebutton,self.translatebelow,self.save_sentence,self.revisebutton]:w.setEnabled(not on)
        self.source.setReadOnly(on or not self.manual_mode.isChecked());self.translation.setReadOnly(on);self.notes.setReadOnly(on);self.reviewcheck.setEnabled(not on);self.savenotes.setEnabled(not on);self.nextbutton.setEnabled(not on)
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item=self.table.item(row,4)
            if item:
                flags=Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable
                if not on:flags|=Qt.ItemFlag.ItemIsUserCheckable
                item.setFlags(flags)
        self.table.blockSignals(False)
        self.runbutton.setText('Đang kiểm tra…' if on else 'Kiểm tra / Tiếp tục')
        self.stopbutton.setEnabled(on)
    def run(self):
        if self.manual_mode.isChecked():return self.translate_source()
        if not self.project:return self.error('Tạo hoặc mở project trước')
        if not self.offline.isChecked() and not self.key.text().strip():return self.error('Nhập Gemini API key hoặc chọn kiểm tra kỹ thuật')
        if not self.model.text().strip():return self.error('Nhập tên model')
        try:model_chain(self.model.text(),self.fallback_models.text())
        except ValueError as exc:return self.error(exc)
        self.project.set_setting('fallback_models',self.fallback_models.text())
        self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text().strip())
        self.last_error=''
        self.worker=Worker(self.project.path,self.key.text().strip(),self.model.text().strip(),self.context.toPlainText(),self.offline.isChecked(),self.fallback_models.text());self.worker.progress.connect(self.status.setText);self.worker.failed.connect(self.run_error);self.worker.updated.connect(self.on_progress);self.worker.finished.connect(self.finished);self.busy(True);self.worker.start()
    def stop(self):
        if self.worker:self.worker.stop.set();self.status.setText('Đang dừng; chờ yêu cầu hiện tại hoàn tất…')
    def run_error(self,message):
        self.last_error=message;self.error(message)
    def finished(self):
        stopped=bool(self.worker and self.worker.stop.is_set())
        self.worker=None;self.busy(False);self.refresh();self.status.setText(self.last_error or ('Đã dừng kiểm tra và lưu tiến độ. Có thể tiếp tục sau.' if stopped else 'Đã lưu tiến độ. Chọn một câu để duyệt kết quả.'))
    def export(self):
        if self.worker:return
        if self.manual_mode.isChecked() and self._manual_result:
            self.save_manual_sentence()
            if self.manual_mode.isChecked():return
        if not self.project or not self.project.rows():return self.error('Chưa có dữ liệu để xuất. Nhập file hoặc dịch và lưu câu vào project trước.')
        path,selected=self.choose_file('Xuất báo cáo','CSV (*.csv);;Excel (*.xlsx)',True)
        if path and not __import__('pathlib').Path(path).suffix:path+='.xlsx' if 'xlsx' in selected else '.csv'
        if path:
            try:self._flush_note_drafts();export_rows(self.project,path);self.status.setText('Đã xuất: '+path)
            except Exception as e:self.error(e)
    def export_training_data(self):
        if self.worker:return
        if not self.project:return self.error('Chưa có bản dịch đã duyệt để xuất dữ liệu train. Duyệt bản sửa trước.')
        path,_=self.choose_file('Xuất dữ liệu đã duyệt để train','JSON Lines (*.jsonl)',True)
        if path and not __import__('pathlib').Path(path).suffix:path+='.jsonl'
        if path:
            try:
                self._flush_note_drafts();count=export_training(self.project,path)
                self.status.setText(f'Đã xuất {count} câu đã review và có bản sửa được duyệt. Chưa chạy huấn luyện.')
            except Exception as e:self.error(e)
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():self.stop();self.error('Đang dừng kiểm tra. Hãy đóng lại khi đã lưu tiến độ.');event.ignore();return
        if self.project:
            if self.manual_mode.isChecked():
                self._manual_source=self.source.toPlainText();self._manual_notes=self.notes.toPlainText();self._save_manual_note_draft()
            self._flush_note_drafts()
            self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text());self.project.set_setting('fallback_models',self.fallback_models.text());self.project.close()
        event.accept()

STYLE = """
QWidget {font-family: 'Arial'; font-size: 13px; color:#24334a;}
QWidget#root {background:#f3f6fb;}
QLabel#title {font-size:24px;font-weight:700;color:#15253f;}
QLabel#muted {color:#6a7890;font-size:12px;}
QLabel#badge {background:#e7edf9;color:#425c90;border-radius:12px;padding:8px 14px;}
QFrame#card {background:white;border:1px solid #e2e8f0;border-radius:12px;}
QLabel#number {font-size:21px;font-weight:700;color:#233e70;}
QLabel#sectionTitle {font-size:17px;font-weight:700;}
QFrame#reviewCard {background:white;border:1px solid #cddaf0;border-radius:12px;}
QLabel#focusTitle {font-size:17px;font-weight:700;color:#204d9b;}
QLabel#activeKey {font-size:11px;color:#718096;}
QTabWidget#reviewTabs::pane {border:1px solid #d9e1ed;border-radius:6px;background:#fff;}
QTabBar::tab {background:#f0f4fb;color:#64748b;padding:7px 12px;border:0;}
QTabBar::tab:selected {background:#e6eeff;color:#245bcc;}
QPushButton#compact {padding:2px 9px;min-height:16px;}
QDialog,QFileDialog {background:#f3f6fb;color:#24334a;}
QDialog QLabel {color:#24334a;}
QDialog QListView,QDialog QTreeView,QDialog QTableView {background:#ffffff;alternate-background-color:#f4f7fb;color:#24334a;selection-background-color:#dce7ff;selection-color:#17345c;}
QDialog QComboBox,QDialog QLineEdit {background:#fff;color:#24334a;}
QComboBox QAbstractItemView {background:white;color:#24334a;selection-background-color:#dce7ff;selection-color:#17345c;}
QDialog QToolButton {background:#edf2fa;color:#24334a;border:1px solid #d6deeb;border-radius:4px;}

QLabel#empty {padding:20px;color:#6a7890;font-size:15px;}
QPushButton {background:white;border:1px solid #d6deeb;border-radius:7px;padding:9px 14px;font-weight:600;}
QPushButton:hover {background:#edf2fd;border-color:#9ab3ec;}
QPushButton:checked {background:#e7efff;color:#245bcc;}
QPushButton#primary {background:#305edb;color:white;border:1px solid #305edb;}
QPushButton#primary:hover {background:#244cbb;}
QPushButton#primary:disabled,QPushButton:disabled {background:#edf0f5;color:#99a3b3;border-color:#e3e7ed;}
QLineEdit,QPlainTextEdit,QComboBox {background:#fff;border:1px solid #d9e1ed;border-radius:7px;padding:8px;selection-background-color:#dce7ff;selection-color:#15253f;}
QLineEdit:focus,QPlainTextEdit:focus {border:1px solid #6388ea;}
QPlainTextEdit:read-only {background:#f7f9fc;}
QComboBox {min-width:125px;}
QTableWidget {background:white;alternate-background-color:#f8faff;border:none;border-radius:10px;selection-background-color:#e5edff;selection-color:#183c81;}
QTableWidget::item {padding:8px;border-bottom:1px solid #edf1f6;}
QHeaderView::section {background:#f0f4fa;color:#62728a;padding:11px 8px;border:none;font-size:12px;font-weight:600;}
QSplitter::handle {background:#f3f6fb;width:16px;}
QProgressBar {border:0;background:#e2e9f4;border-radius:5px;text-align:center;min-height:20px;font-size:11px;}
QProgressBar::chunk {background:#9fb8fa;border-radius:5px;}
QCheckBox {spacing:7px;}
QToolTip {background:white;color:#24334a;border:1px solid #d9e1ed;padding:5px;}
"""

def main():
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app=QApplication(sys.argv);app.setStyle('Fusion');window=Window()
    if len(sys.argv)>1 and sys.argv[1].endswith('.lqa'):window.attach(sys.argv[1])
    window.show();sys.exit(app.exec())
