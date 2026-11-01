import json, sys, threading
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QLineEdit,QPlainTextEdit,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QCheckBox,QInputDialog,QSplitter,QFrame,QComboBox,QProgressBar,QHeaderView,QAbstractItemView,QScrollArea,QMenu)
from PySide6.QtGui import QColor
from .core import Project,load_csv,technical,fingerprint,export_rows,export_training

DEFAULT_MODEL = 'gemini-3.5-flash-lite'

class Worker(QThread):
    progress=Signal(str)
    updated=Signal(int,int)
    failed=Signal(str)
    def __init__(self,path,key,model,context,offline):
        super().__init__();self.args=(path,key,model,context,offline);self.stop=threading.Event()
    def run(self):
        p=None;client=None
        try:
            path,key,model,context,offline=self.args;p=Project(path)
            if not offline:
                from .gemini import Gemini
                client=Gemini(key)
            pending=[r for r in p.rows() if not r['reviewed']]
            self.updated.emit(0,len(pending))
            for index,row in enumerate(pending):
                if self.stop.is_set():break
                if row['reviewed']:continue
                issues=technical(row['english'],row['vietnamese'])
                if offline:
                    result={'status':'REVIEW','issues':issues,'reason':'Chỉ kiểm tra kỹ thuật; chưa đánh giá ngôn ngữ.','suggestion':''}
                else:
                    h=fingerprint(row,model,context);result=p.cached(h)
                    if result is None:
                        for attempt in range(3):
                            try:result=client.review(row,model,context);break
                            except Exception as exc:
                                code=getattr(exc,'code',None)
                                if str(code) not in ['429','500','502','503','504'] or attempt==2:raise
                                self.progress.emit(f'Dịch vụ bận ({code}); thử lại sau {15*(attempt+1)} giây…')
                                if self.stop.wait(15*(attempt+1)):return
                        p.cache(h,result)
                    if issues:result={**result,'status':'FAIL' if result['status']=='FAIL' or 'Placeholder không khớp' in issues or 'Thiếu bản dịch tiếng Việt' in issues else 'REVIEW','issues':issues+result['issues']}
                    if self.stop.is_set():break
                p.save_result(row['key'],result);self.progress.emit('Đã lưu: '+row['key']);self.updated.emit(index+1,len(pending))
                if not offline and index+1<len(pending) and self.stop.wait(5):break
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
        self.project=None;self.worker=None;self.data=[];self.last_error='';self.file_dialogs=[];self._selected_key=None;self._note_drafts={};self._loading_feedback=False
        root=QWidget();root.setObjectName('root');self.setCentralWidget(root)
        layout=QVBoxLayout(root);layout.setContentsMargins(28,22,28,18);layout.setSpacing(16)
        header=QHBoxLayout();layout.addLayout(header)
        brand=QVBoxLayout();title=QLabel('Localization QA');title.setObjectName('title');brand.addWidget(title)
        subtitle=QLabel('Không bỏ sót ý nghĩa. Giữ câu chữ tự nhiên.');subtitle.setObjectName('muted');brand.addWidget(subtitle);header.addLayout(brand);header.addStretch()
        self.project_label=QLabel('Chưa mở project');self.project_label.setObjectName('badge');header.addWidget(self.project_label)
        self.configbutton=QPushButton('Cấu hình Gemini');self.configbutton.setCheckable(True);header.addWidget(self.configbutton)
        bar=QHBoxLayout();layout.addLayout(bar);self.actions=[]
        for label,fn in [('＋ Tạo project',self.new),('Mở project',self.open),('Nhập dữ liệu',self.import_csv),('Xuất báo cáo',self.export),('Xuất dữ liệu train',self.export_training_data),('Nhập bảng so sánh',self.import_comparison_csv)]:
            b=QPushButton(label)
            b.clicked.connect(fn)
            bar.addWidget(b);self.actions.append(b)
        bar.addStretch();step=QLabel('01  Nhập dữ liệu    →    02  Kiểm tra    →    03  Duyệt & xuất');step.setObjectName('muted');bar.addWidget(step)
        self.settings=QFrame();self.settings.setObjectName('card');cfg=QVBoxLayout(self.settings);cfg.setContentsMargins(18,14,18,14);cfg.setSpacing(10)
        layout.addWidget(self.settings);self.configbutton.toggled.connect(self.settings.setVisible)
        line=QHBoxLayout();cfg.addLayout(line)
        self.key=QLineEdit();self.key.setEchoMode(QLineEdit.EchoMode.Password);self.key.setPlaceholderText('Dán Gemini API key vào đây');line.addWidget(self.key,2)
        for label,fn in [('Lưu key',self.save_key),('Xóa key',self.delete_key)]:
            b=QPushButton(label);b.clicked.connect(fn);line.addWidget(b)
        line.addWidget(QLabel('Model'))
        self.model=QLineEdit(DEFAULT_MODEL);self.model.setMinimumWidth(230);line.addWidget(self.model)
        self.context=QPlainTextEdit();self.context.setPlaceholderText('Ngữ cảnh và thuật ngữ • Ví dụ: App gấp giấy cho người mới. unfold = mở nếp gấp. Giọng văn ngắn gọn, thân thiện.');self.context.setFixedHeight(65);cfg.addWidget(self.context)
        note=QLabel('Key lưu trong kho bảo mật của máy. Khi dùng AI, câu dịch và ngữ cảnh được gửi đến Google; hạn mức theo tài khoản.');note.setWordWrap(True);note.setObjectName('muted');cfg.addWidget(note)
        try:
            import keyring
            self.key.setText(keyring.get_password('LocalizationQA','gemini') or '')
        except Exception:pass
        self.configbutton.setChecked(not bool(self.key.text()));self.settings.setVisible(self.configbutton.isChecked())
        stats=QHBoxLayout();layout.addLayout(stats);self.stat_labels=[]
        for name in ['TỔNG SỐ CÂU','CẦN XEM LẠI','LỖI RÕ RÀNG','ĐÃ REVIEW']:
            card=QFrame();card.setObjectName('card');box=QVBoxLayout(card);box.setContentsMargins(16,10,16,10)
            number=QLabel('0');number.setObjectName('number');box.addWidget(number);label=QLabel(name);label.setObjectName('muted');box.addWidget(label);stats.addWidget(card);self.stat_labels.append(number)
        filters=QHBoxLayout();layout.addLayout(filters)
        self.search=QLineEdit();self.search.setPlaceholderText('Tìm key, câu tiếng Anh hoặc tiếng Việt…');self.search.textChanged.connect(self.filter_rows);filters.addWidget(self.search,2)
        self.filter=QComboBox();self.filter.addItems(['Tất cả','Cần xem lại','Lỗi rõ ràng','Chưa kiểm tra','Đã review','Chưa review']);self.filter.currentIndexChanged.connect(self.filter_rows);filters.addWidget(self.filter)
        self.offline=QCheckBox('Chỉ kiểm tra kỹ thuật');filters.addWidget(self.offline)
        self.runbutton=QPushButton('Bắt đầu kiểm tra');self.runbutton.setObjectName('primary');self.runbutton.clicked.connect(self.run);filters.addWidget(self.runbutton)
        self.stopbutton=QPushButton('Dừng');self.stopbutton.clicked.connect(self.stop);self.stopbutton.setEnabled(False);filters.addWidget(self.stopbutton)
        splitter=QSplitter(Qt.Orientation.Horizontal);layout.addWidget(splitter,1)
        left=QFrame();left.setObjectName('card');leftbox=QVBoxLayout(left);leftbox.setContentsMargins(0,0,0,0)
        self.empty=QLabel('Bắt đầu với một project mới\n\nNhập CSV, JSON hoặc Word có cặp câu Anh–Việt.\nChọn cả hai file JSON Anh và Việt cùng lúc trong Nhập dữ liệu.\nKết quả được lưu để tiếp tục trên Mac hoặc Windows.');self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter);self.empty.setObjectName('empty');leftbox.addWidget(self.empty)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Key','Tiếng Anh','Tiếng Việt','Đánh giá','Đã review','Ghi chú','Local','Gemini']);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.table.setAlternatingRowColors(True);self.table.setShowGrid(False);self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.itemSelectionChanged.connect(self.select);self.table.itemChanged.connect(self.table_feedback_changed);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.table.horizontalHeader().setStretchLastSection(True);leftbox.addWidget(self.table);splitter.addWidget(left)
        panel=QFrame();panel.setObjectName('card');right=QVBoxLayout(panel);right.setContentsMargins(18,16,18,16);right.setSpacing(10)
        self.rowtitle=QLabel('Chọn một câu để review');self.rowtitle.setObjectName('sectionTitle');self.rowtitle.setWordWrap(True);right.addWidget(self.rowtitle)
        right.addWidget(QLabel('TIẾNG ANH'))
        self.source=QPlainTextEdit();self.source.setReadOnly(True);self.source.setMinimumHeight(60);self.source.setMaximumHeight(110);right.addWidget(self.source)
        right.addWidget(QLabel('BẢN DỊCH HIỆN TẠI'))
        self.current=QPlainTextEdit();self.current.setReadOnly(True);self.current.setMinimumHeight(60);self.current.setMaximumHeight(110);right.addWidget(self.current)
        right.addWidget(QLabel('NHẬN XÉT & NGỮ CẢNH'))
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMinimumHeight(100);right.addWidget(self.detail,1)
        right.addWidget(QLabel('GHI CHÚ CỦA BẠN'))
        self.notes=QPlainTextEdit();self.notes.setPlaceholderText('Ví dụ: Gợi ý vẫn khó hiểu; cần sửa thuật ngữ…');self.notes.setMinimumHeight(60);self.notes.setMaximumHeight(80);self.notes.textChanged.connect(self.note_edited);right.addWidget(self.notes)
        feedbackbar=QHBoxLayout();right.addLayout(feedbackbar)
        self.reviewcheck=QCheckBox('Đã review');self.reviewcheck.setToolTip('Đã xem câu; chưa có nghĩa là bản sửa được duyệt để train.');self.reviewcheck.toggled.connect(self.review_toggled);feedbackbar.addWidget(self.reviewcheck)
        self.savenotes=QPushButton('Lưu ghi chú');self.savenotes.clicked.connect(self.save_review_notes);feedbackbar.addWidget(self.savenotes)
        final_label=QLabel('BẢN SỬA CUỐI • CHỈ DÙNG ĐỂ TRAIN SAU KHI DUYỆT');final_label.setWordWrap(True);right.addWidget(final_label)
        self.translation=QPlainTextEdit();self.translation.setMinimumHeight(80);self.translation.setPlaceholderText('Đề xuất AI hoặc bản sửa của bạn');right.addWidget(self.translation,1)
        self.approvebutton=QPushButton('✓ Duyệt bản sửa và lưu');self.approvebutton.setObjectName('primary');self.approvebutton.clicked.connect(self.approve);right.addWidget(self.approvebutton)
        self.nextbutton=QPushButton('Câu tiếp theo chưa review →');self.nextbutton.clicked.connect(self.next_row);right.addWidget(self.nextbutton);panel.setMinimumHeight(780);reviewscroll=QScrollArea();reviewscroll.setWidgetResizable(True);reviewscroll.setWidget(panel);reviewscroll.setFrameShape(QFrame.Shape.NoFrame);splitter.addWidget(reviewscroll);splitter.setSizes([850,420])
        footer=QHBoxLayout();layout.addLayout(footer);self.status=QLabel('Sẵn sàng • Tạo hoặc mở project để bắt đầu.');self.status.setWordWrap(True);footer.addWidget(self.status,1)
        self.progressbar=QProgressBar();self.progressbar.setRange(0,1);self.progressbar.setValue(0);self.progressbar.setFixedWidth(220);self.progressbar.setFormat('%v / %m câu');footer.addWidget(self.progressbar)
        self.setStyleSheet(STYLE)
        self.refresh_controls()
    def refresh_controls(self):
        has=bool(self.project);running=bool(self.worker)
        for w in self.actions[2:]+[self.runbutton]:w.setEnabled(has and not running)
        selected=0<=self.table.currentRow()<len(self.data)
        self.approvebutton.setEnabled(selected and not running);self.translation.setReadOnly(running or not selected);self.nextbutton.setEnabled(selected and not running)
        self.notes.setReadOnly(running or not selected);self.reviewcheck.setEnabled(selected and not running);self.savenotes.setEnabled(selected and not running)
    def filter_rows(self):
        query=self.search.text().casefold();mode=self.filter.currentIndex()
        for i,r in enumerate(self.data):
            result=json.loads(r['result']) if r['result'] else {};status=result.get('status','')
            match=[True,status=='REVIEW',status=='FAIL',not r['result'],bool(r['reviewed']),not r['reviewed']][mode]
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
                self.table.selectRow(i);self.table.scrollToItem(self.table.item(i,0));return
        self.status.setText('Không còn câu chưa review trong bộ lọc hiện tại.')
    def on_progress(self,done,total):
        self.progressbar.setRange(0,max(1,total));self.progressbar.setValue(done)
        self.refresh()
    def error(self,e):QMessageBox.warning(self,'Thông báo',str(e))
    def attach(self,path):
        try:
            p=Project(path)
            if self.project:
                self._flush_note_drafts()
                self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text());self.project.close()
            self._selected_key=None;self._note_drafts.clear()
            self.project=p;self.context.setPlainText(p.setting('context'));self.model.setText(p.setting('model',DEFAULT_MODEL));self.project_label.setText(__import__('pathlib').Path(path).name);self.project_label.setToolTip(path);self.refresh();self.status.setText('Project đã mở • '+path)
        except Exception as e:self.error(e)
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
        path,_=self.choose_file('Mở project','Project (*.lqa)')
        if path:self.attach(path)
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
    def apply_input_rows(self, rows, report=None):
        if not rows:raise ValueError('File chưa có cặp câu nào để nhập')
        if not self.confirm_input_report(rows, report or {}):
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
    def import_selected_paths(self, paths):
        """Finish parsing and role selection before any project write."""
        from pathlib import Path
        from .input_json import load_json,load_json_pair,SingleLanguageJSONError
        if not paths:return False
        if len(paths)>2:raise ValueError('Chọn một file CSV/Word/JSON song ngữ hoặc đúng hai file JSON Anh–Việt.')
        paths=[Path(path) for path in paths];report={}
        if len(paths)==2:
            if any(path.suffix.lower()!='.json' for path in paths):
                raise ValueError('Chỉ chọn nhiều file khi nhập hai JSON Anh–Việt. CSV và Word cần chọn từng file.')
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
            elif suffix in ('.docx','.doc'):
                from .input_word import load_word
                rows=load_word(str(path))
            else:raise ValueError('Chọn CSV, JSON, DOCX hoặc DOC. Có thể chọn cùng lúc hai JSON Anh–Việt.')
        imported=self.apply_input_rows(rows,report)
        if imported:
            self.status.setText(self.status.text()+' Nguồn: '+' + '.join(path.name for path in sources))
            self.status.setToolTip('\n'.join(str(path) for path in sources))
        return imported
    def import_csv(self):
        """Retain the callback name; the primary input now accepts one or two files."""
        if not self.project or self.worker:return self.error('Tạo hoặc mở project trước; dừng kiểm tra nếu đang chạy')
        paths=self.choose_files('Chọn dữ liệu • Có thể chọn cùng lúc hai JSON Anh–Việt',
            'Dữ liệu (*.csv *.json *.docx *.doc);;JSON Anh–Việt (*.json);;CSV (*.csv);;Word (*.docx *.doc)')
        if not paths:return
        try:self.import_selected_paths(paths)
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
        if not self.project or self.worker:return self.error('Tạo hoặc mở project trước')
        path,_=self.choose_file('Nhập bảng so sánh Local–Gemini','CSV (*.csv)')
        if path:
            try:
                from .comparison import import_comparison
                self._flush_note_drafts();count=import_comparison(self.project,path);self._note_drafts.clear();self.refresh();self.status.setText(f'Đã nhập {count} câu so sánh. Chưa tự duyệt bản sửa nào.')
            except Exception as e:self.error(e)
    def refresh(self):
        if not self.project:return
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
        self.table.setColumnWidth(0,120);self.table.setColumnWidth(1,240);self.table.setColumnWidth(2,240);self.table.setColumnWidth(3,120);self.table.setColumnWidth(4,90);self.table.setColumnWidth(5,180);self.table.setColumnWidth(6,240);self.table.setColumnWidth(7,240)
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
        i=self.table.currentRow()
        if i<0 or i>=len(self.data):
            self.rowtitle.setText('Chọn một câu để review')
            self._selected_key=None;self._loading_feedback=True
            for field in [self.source,self.current,self.detail,self.translation,self.notes]:field.clear()
            self.reviewcheck.setChecked(False);self._loading_feedback=False
            self.refresh_controls();return
        r=self.data[i];result=json.loads(r['result']) if r['result'] else {}
        self._selected_key=r['key'];self._loading_feedback=True
        self.notes.setPlainText(self._note_drafts.get(r['key'],r.get('notes','')));self.reviewcheck.setChecked(bool(r['reviewed']));self._loading_feedback=False
        self.rowtitle.setText(r['key']);self.source.setPlainText(r['english']);self.current.setPlainText(r['vietnamese'])
        backend=self.project.backend_results(r['key']);comparison=backend.get('comparison',{})
        message='\n'.join('• '+issue for issue in result.get('issues',[]))
        if comparison:
            message+='\nSo sánh: '+comparison.get('reason','')+'\nCần thêm ngữ cảnh: '+comparison.get('context_needed','')
        self.detail.setPlainText(message+'\n'+result.get('reason','Chưa có đánh giá QA riêng; đang xem kết quả so sánh.' if comparison else 'Chưa kiểm tra. Bạn có thể tự review hoặc bắt đầu kiểm tra AI.')+'\n\nNgữ cảnh: '+(r['context'] or 'Chưa cung cấp'))
        self.translation.setPlainText(r['approved'] if r['approved'] is not None else result.get('suggestion') or r['vietnamese']);self.refresh_controls()
    def note_edited(self):
        if not self._loading_feedback and self._selected_key and not self.worker:
            self._note_drafts[self._selected_key]=self.notes.toPlainText()
    def _flush_note_drafts(self):
        if self.project:
            for key,note in self._note_drafts.items():self.project.save_notes(key,note)
        self._note_drafts.clear()
    def save_review_notes(self):
        if not self.project or not self._selected_key or self.worker:return
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
            self.project.approve(self.data[i]['key'],text);self.refresh();self.status.setText('Đã lưu bản dịch được duyệt.');self.next_row()
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
        for w in self.actions+[self.runbutton,self.approvebutton,self.context,self.model,self.offline]:w.setEnabled(not on)
        self.translation.setReadOnly(on);self.notes.setReadOnly(on);self.reviewcheck.setEnabled(not on);self.savenotes.setEnabled(not on);self.nextbutton.setEnabled(not on)
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
        if not self.project:return self.error('Tạo hoặc mở project trước')
        if not self.offline.isChecked() and not self.key.text().strip():return self.error('Nhập Gemini API key hoặc chọn kiểm tra kỹ thuật')
        if not self.model.text().strip():return self.error('Nhập tên model')
        self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text().strip())
        self.last_error=''
        self.worker=Worker(self.project.path,self.key.text().strip(),self.model.text().strip(),self.context.toPlainText(),self.offline.isChecked());self.worker.progress.connect(self.status.setText);self.worker.failed.connect(self.run_error);self.worker.updated.connect(self.on_progress);self.worker.finished.connect(self.finished);self.busy(True);self.worker.start()
    def stop(self):
        if self.worker:self.worker.stop.set();self.status.setText('Đang dừng; chờ yêu cầu hiện tại hoàn tất…')
    def run_error(self,message):
        self.last_error=message;self.error(message)
    def finished(self):
        self.worker=None;self.busy(False);self.refresh();self.status.setText(self.last_error or 'Đã lưu tiến độ. Chọn một câu để duyệt kết quả.')
    def export(self):
        if not self.project:return
        path,selected=self.choose_file('Xuất báo cáo','CSV (*.csv);;Excel (*.xlsx)',True)
        if path and not __import__('pathlib').Path(path).suffix:path+='.xlsx' if 'xlsx' in selected else '.csv'
        if path:
            try:self._flush_note_drafts();export_rows(self.project,path);self.status.setText('Đã xuất: '+path)
            except Exception as e:self.error(e)
    def export_training_data(self):
        if not self.project or self.worker:return
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
            self._flush_note_drafts()
            self.project.set_setting('context',self.context.toPlainText());self.project.set_setting('model',self.model.text());self.project.close()
        event.accept()

STYLE = """
QWidget {font-family: 'Arial'; font-size: 13px; color:#24334a;}
QWidget#root {background:#f3f6fb;}
QLabel#title {font-size:27px;font-weight:700;color:#15253f;}
QLabel#muted {color:#6a7890;font-size:12px;}
QLabel#badge {background:#e7edf9;color:#425c90;border-radius:12px;padding:8px 14px;}
QFrame#card {background:white;border:1px solid #e2e8f0;border-radius:12px;}
QLabel#number {font-size:27px;font-weight:700;color:#233e70;}
QLabel#sectionTitle {font-size:17px;font-weight:700;}
QLabel#empty {padding:50px;color:#6a7890;font-size:15px;}
QPushButton {background:white;border:1px solid #d6deeb;border-radius:7px;padding:9px 14px;font-weight:600;}
QPushButton:hover {background:#edf2fd;border-color:#9ab3ec;}
QPushButton:checked {background:#e7efff;color:#245bcc;}
QPushButton#primary {background:#305edb;color:white;border:1px solid #305edb;}
QPushButton#primary:hover {background:#244cbb;}
QPushButton:disabled {background:#edf0f5;color:#99a3b3;border-color:#e3e7ed;}
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
