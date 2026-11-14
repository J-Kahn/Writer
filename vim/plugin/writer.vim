" Writer.vim - Vim integration for Writer environment
" Communicates with side panels via files in ~/.writer/

if exists('g:loaded_writer')
    finish
endif
let g:loaded_writer = 1

" ============================================================================
" Configuration
" ============================================================================

let g:writer_dir = expand('~/.writer')
let g:writer_context_file = g:writer_dir . '/context.json'
let g:writer_preview_file = g:writer_dir . '/preview_state.json'
let g:writer_enabled = 1
let g:writer_python_dir = ''

" Path to this plugin's python/ dir, resolved at load time. resolve() matters:
" setup.sh symlinks this file into ~/.vim/plugin, and the python/ dir lives next
" to the real file, not next to the symlink.
let s:script_dir = fnamemodify(resolve(expand('<sfile>:p')), ':h')
let s:plugin_python_dir = fnamemodify(s:script_dir, ':h:h') . '/python'

" Preview state
let s:preview_active = 0
let s:preview_text = ''
let s:preview_line = 0
let s:preview_ns = 0

" ============================================================================
" Setup Function (called by launcher)
" ============================================================================

function! writer#Setup(python_dir, filename) abort
    let g:writer_python_dir = a:python_dir

    " Ensure directory exists
    call mkdir(g:writer_dir, 'p')

    " Create namespace for virtual text if available
    if has('nvim')
        let s:preview_ns = nvim_create_namespace('writer_preview')
    endif

    " Write initial context
    call s:WriteContext()

    " Set up autocommands
    call s:SetupAutocommands()

    echo "Writer: Ready. <Leader>ws suggestions, <Leader>wf fill, <Leader>wr review."
endfunction

" ============================================================================
" Context Writing
" ============================================================================

function! s:WriteContext() abort
    if !g:writer_enabled
        return
    endif

    let l:lines = getline(1, '$')
    let l:cursor_line = line('.')
    let l:cursor_col = col('.')

    " Get context around cursor
    let l:start = max([1, l:cursor_line - 50])
    let l:end = min([len(l:lines), l:cursor_line + 10])

    let l:context = {
        \ 'lines': l:lines,
        \ 'cursor_line': l:cursor_line,
        \ 'cursor_col': l:cursor_col,
        \ 'before': l:lines[l:start-1 : l:cursor_line-2],
        \ 'current': get(l:lines, l:cursor_line-1, ''),
        \ 'after': l:lines[l:cursor_line : l:end-1],
        \ 'filename': expand('%:p'),
        \ 'timestamp': localtime()
        \ }

    call writefile([json_encode(l:context)], g:writer_context_file)
endfunction

" ============================================================================
" Outline Extraction (for fill section)
" ============================================================================

function! s:GetDocumentOutline() abort
    let l:outline = []
    let l:lines = getline(1, '$')

    for l:line in l:lines
        " Match markdown headings
        let l:match = matchlist(l:line, '^\(#\+\)\s\+\(.*\)$')
        if !empty(l:match)
            call add(l:outline, l:match[2])
        endif
    endfor

    return l:outline
endfunction

function! s:GetCurrentHeading() abort
    " Find the heading above current cursor position
    let l:cur_line = line('.')

    for l:lnum in range(l:cur_line, 1, -1)
        let l:line = getline(l:lnum)
        let l:match = matchlist(l:line, '^\(#\+\)\s\+\(.*\)$')
        if !empty(l:match)
            return {'line': l:lnum, 'level': len(l:match[1]), 'text': l:match[2]}
        endif
    endfor

    return {}
endfunction

" ============================================================================
" Preview Functions
" ============================================================================

function! s:ShowPreview() abort
    " Read preview state
    if !filereadable(g:writer_preview_file)
        return
    endif

    let l:content = join(readfile(g:writer_preview_file), '')
    let l:state = json_decode(l:content)

    if empty(l:state) || empty(get(l:state, 'text', ''))
        return
    endif

    let s:preview_text = l:state.text
    let s:preview_line = line('.')
    let s:preview_active = 1

    " Show preview using virtual text (Neovim) or echo (Vim)
    if has('nvim')
        call s:ShowVirtualTextPreview()
    else
        call s:ShowPopupPreview()
    endif
endfunction

function! s:ShowVirtualTextPreview() abort
    " Clear previous
    call nvim_buf_clear_namespace(0, s:preview_ns, 0, -1)

    " Add virtual text after current line
    let l:preview_lines = split(s:preview_text, '\n')
    let l:display_text = ' ' . l:preview_lines[0]
    if len(l:preview_lines) > 1
        let l:display_text .= ' [+' . (len(l:preview_lines) - 1) . ' lines]'
    endif

    call nvim_buf_set_extmark(0, s:preview_ns, s:preview_line - 1, 0, {
        \ 'virt_text': [[l:display_text, 'Comment']],
        \ 'virt_text_pos': 'eol'
        \ })
endfunction

function! s:ShowPopupPreview() abort
    " For regular Vim, show in a popup or echo
    if exists('*popup_create')
        " Close existing popup
        call popup_clear()

        let l:preview_lines = split(s:preview_text, '\n')
        " Limit preview length
        if len(l:preview_lines) > 5
            let l:preview_lines = l:preview_lines[:4] + ['...']
        endif

        call popup_create(l:preview_lines, {
            \ 'line': 'cursor+1',
            \ 'col': 'cursor',
            \ 'border': [],
            \ 'padding': [0, 1, 0, 1],
            \ 'highlight': 'Pmenu',
            \ 'borderhighlight': ['Comment'],
            \ 'close': 'click',
            \ 'moved': 'any'
            \ })
    else
        " Fallback to echo
        let l:short = s:preview_text[:80]
        if len(s:preview_text) > 80
            let l:short .= '...'
        endif
        echo "Preview: " . l:short
    endif
endfunction

function! s:ClearPreview() abort
    let s:preview_active = 0
    let s:preview_text = ''

    if has('nvim')
        call nvim_buf_clear_namespace(0, s:preview_ns, 0, -1)
    elseif exists('*popup_clear')
        call popup_clear()
    endif

    echo "Writer: Preview cleared"
endfunction

function! s:AcceptPreview() abort
    if !s:preview_active || empty(s:preview_text)
        echo "Writer: No preview to accept"
        return
    endif

    " Check mode
    let l:mode_file = g:writer_dir . '/suggestion_mode.txt'
    let l:mode = 'next_paragraph'
    if filereadable(l:mode_file)
        let l:mode = get(readfile(l:mode_file), 0, 'next_paragraph')
    endif

    let l:lines = split(s:preview_text, '\n')

    if l:mode == 'alternatives'
        " Replace current paragraph
        call s:ReplaceCurrentParagraph(l:lines)
        echo "Writer: Paragraph replaced"
    else
        " Insert as new paragraph
        call append(line('.'), [''] + l:lines)
        normal! j
        echo "Writer: Paragraph inserted"
    endif

    call s:ClearPreview()
endfunction

" ============================================================================
" User Commands
" ============================================================================

function! writer#RequestSuggestions() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Write current context
    call s:WriteContext()

    " Signal suggestions panel
    let l:signal_file = g:writer_dir . '/request_suggestions'
    call writefile([string(localtime())], l:signal_file)

    echo "Writer: Requesting paragraph suggestions..."
endfunction

function! writer#RefreshOutline() abort
    call s:WriteContext()
    let l:signal_file = g:writer_dir . '/request_outline'
    call writefile([string(localtime())], l:signal_file)
    echo "Writer: Refreshing outline..."
endfunction

function! writer#FillSection() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Get current heading
    let l:heading = s:GetCurrentHeading()
    if empty(l:heading)
        echo "Writer: No heading found. Place cursor under a heading."
        return
    endif

    " Check if section has content (non-empty lines until next heading)
    let l:has_content = 0
    let l:cur_line = l:heading.line + 1
    let l:total_lines = line('$')

    while l:cur_line <= l:total_lines
        let l:line = getline(l:cur_line)
        " Check for next heading
        if l:line =~ '^#'
            break
        endif
        " Check for non-empty content
        if l:line =~ '\S'
            let l:has_content = 1
            break
        endif
        let l:cur_line += 1
    endwhile

    if l:has_content
        let l:confirm = confirm("Section '" . l:heading.text . "' has content. Generate anyway?", "&Yes\n&No", 2)
        if l:confirm != 1
            return
        endif
    endif

    " Write current context first
    call s:WriteContext()

    " Get outline
    let l:outline = s:GetDocumentOutline()

    " Create fill request
    let l:request = {
        \ 'heading': l:heading.text,
        \ 'heading_line': l:heading.line,
        \ 'heading_level': l:heading.level,
        \ 'outline': l:outline
        \ }

    let l:request_file = g:writer_dir . '/request_fill_section'
    call writefile([json_encode(l:request)], l:request_file)

    echo "Writer: Generating content for '" . l:heading.text . "'..."
endfunction

function! writer#InsertSuggestion(num) abort
    let l:suggestion_file = g:writer_dir . '/suggestion_' . a:num . '.txt'
    let l:mode_file = g:writer_dir . '/suggestion_mode.txt'

    if !filereadable(l:suggestion_file)
        echo "Writer: No suggestion " . a:num . " available"
        return
    endif

    let l:lines = readfile(l:suggestion_file)
    if empty(l:lines)
        echo "Writer: Suggestion " . a:num . " is empty"
        return
    endif

    " Check mode
    let l:mode = 'next_paragraph'
    if filereadable(l:mode_file)
        let l:mode = get(readfile(l:mode_file), 0, 'next_paragraph')
    endif

    if l:mode == 'alternatives'
        " Replace current paragraph
        call s:ReplaceCurrentParagraph(l:lines)
        echo "Writer: Replaced paragraph with alternative " . a:num
    else
        " Insert as new paragraph after current line
        call append(line('.'), [''] + l:lines)
        normal! j
        echo "Writer: Inserted paragraph " . a:num
    endif

    " Clear preview
    call s:ClearPreview()
endfunction

function! s:ReplaceCurrentParagraph(new_lines) abort
    " Find paragraph boundaries (blank lines)
    let l:cur = line('.')
    let l:start = l:cur
    let l:end = l:cur

    " Find start of paragraph (search backwards for blank line or start of file)
    while l:start > 1
        let l:prev = getline(l:start - 1)
        if l:prev =~ '^\s*$'
            break
        endif
        let l:start -= 1
    endwhile

    " Find end of paragraph (search forwards for blank line or end of file)
    let l:total = line('$')
    while l:end < l:total
        let l:next = getline(l:end + 1)
        if l:next =~ '^\s*$'
            break
        endif
        let l:end += 1
    endwhile

    " Delete old paragraph and insert new
    execute l:start . ',' . l:end . 'delete _'
    call append(l:start - 1, a:new_lines)

    " Position cursor at start of new paragraph
    execute l:start
endfunction

function! writer#PreviewNext() abort
    let l:signal_file = g:writer_dir . '/preview_next'
    call writefile([string(localtime())], l:signal_file)

    " Wait a bit for panel to update
    sleep 100m
    call s:ShowPreview()
endfunction

function! writer#PreviewPrev() abort
    let l:signal_file = g:writer_dir . '/preview_prev'
    call writefile([string(localtime())], l:signal_file)

    " Wait a bit for panel to update
    sleep 100m
    call s:ShowPreview()
endfunction

function! writer#Toggle() abort
    let g:writer_enabled = !g:writer_enabled
    echo "Writer: " . (g:writer_enabled ? "Enabled" : "Disabled")
endfunction

function! writer#RequestReview() abort
    if !g:writer_enabled
        echo "Writer: Disabled"
        return
    endif

    " Write current context first
    call s:WriteContext()

    " Signal review panel
    let l:signal_file = g:writer_dir . '/request_review'
    call writefile([string(localtime())], l:signal_file)

    echo "Writer: Requesting document review..."
endfunction

" ============================================================================
" Autocommands
" ============================================================================

function! s:SetupAutocommands() abort
    augroup Writer
        autocmd!
        " Update context periodically and on save
        autocmd CursorHold,CursorHoldI * call s:WriteContext()
        autocmd BufWritePost * call s:WriteContext()
        autocmd TextChanged,TextChangedI * call s:WriteContext()

        " Clear preview on cursor move
        autocmd CursorMoved,CursorMovedI * if s:preview_active && line('.') != s:preview_line | call s:ClearPreview() | endif

        " Refresh preview display periodically
        autocmd CursorHold * if s:preview_active | call s:ShowPreview() | endif
    augroup END
endfunction

" ============================================================================
" Citations
" ============================================================================

" Resolve the citation CLI. g:writer_python_dir is set by the launcher; fall
" back to the plugin's own location so :WriterCite works in a bare vim too.
function! s:CiteCli() abort
    if !empty(g:writer_python_dir)
        let l:path = g:writer_python_dir . '/cite_cli.py'
        if filereadable(l:path)
            return l:path
        endif
    endif
    return s:plugin_python_dir . '/cite_cli.py'
endfunction

" Run a cite_cli subcommand and return the decoded JSON ({} on failure).
function! s:CiteRun(args) abort
    let l:cmd = 'python3 ' . shellescape(s:CiteCli()) . ' ' . a:args
    let l:output = system(l:cmd)
    if empty(l:output)
        return {'error': 'No response from cite_cli.py'}
    endif
    try
        return json_decode(l:output)
    catch
        return {'error': substitute(l:output, '\n', ' ', 'g')}
    endtry
endfunction

" The .bib this buffer writes to: g:writer_bib_file if set, else derived from
" \bibliography{} / \addbibresource{} / a neighbouring .bib.
function! s:BibFile() abort
    if exists('g:writer_bib_file') && !empty(g:writer_bib_file)
        return g:writer_bib_file
    endif
    let l:result = s:CiteRun('bibpaths --doc ' . shellescape(expand('%:p')))
    let l:paths = get(l:result, 'paths', [])
    return empty(l:paths) ? '' : l:paths[0]
endfunction

function! s:FormatResult(item) abort
    let l:authors = get(a:item, 'authors', [])
    let l:who = empty(l:authors) ? '?' : l:authors[0]
    if len(l:authors) > 2
        let l:who .= ' et al.'
    elseif len(l:authors) == 2
        let l:who .= ' & ' . l:authors[1]
    endif
    let l:year = get(a:item, 'year', '')
    let l:journal = get(a:item, 'journal', '')
    let l:line = l:who . ' (' . (empty(l:year) ? 'n.d.' : l:year) . ') ' . get(a:item, 'title', '')
    if !empty(l:journal)
        let l:line .= ' [' . l:journal . ']'
    endif
    return l:line
endfunction

" Fetch the BibTeX for a result, append it to the .bib, insert \cite{key}.
function! s:CiteChoice(index) abort
    if a:index <= 0 || a:index > len(s:cite_results)
        return
    endif
    let l:item = s:cite_results[a:index - 1]
    let l:doi = get(l:item, 'doi', '')
    if empty(l:doi)
        echohl WarningMsg | echo 'Writer: That result has no DOI' | echohl None
        return
    endif

    let l:bib = s:BibFile()
    if empty(l:bib)
        echohl ErrorMsg
        echo 'Writer: No .bib found. Set g:writer_bib_file or add \bibliography{} to the document.'
        echohl None
        return
    endif

    echo 'Writer: Fetching BibTeX...'
    let l:res = s:CiteRun('cite --doi ' . shellescape(l:doi) . ' --bib ' . shellescape(l:bib))
    if has_key(l:res, 'error')
        echohl ErrorMsg | echo 'Writer: ' . l:res.error | echohl None
        return
    endif

    call s:InsertCite(l:res.cite_key)
    let l:note = get(l:res, 'duplicate', 0) ? ' (already in ' : ' (added to '
    echo 'Writer: \cite{' . l:res.cite_key . '}' . l:note . fnamemodify(l:bib, ':t') . ')'
endfunction

" Insert \cite{key} at the cursor, or extend an existing \cite{...} group.
function! s:InsertCite(key) abort
    let l:line = getline('.')
    let l:col = col('.')
    let l:before = strpart(l:line, 0, l:col)
    let l:open = strridx(l:before, '\cite{')
    let l:close = stridx(l:line, '}', l:col - 1)

    if l:open >= 0 && l:close >= 0 && stridx(l:before[l:open :], '}') < 0
        " Cursor sits inside \cite{...} - add this key to the group
        let l:inner = strpart(l:line, l:open + 6, l:close - l:open - 6)
        let l:sep = empty(trim(l:inner)) ? '' : ','
        let l:new = strpart(l:line, 0, l:close) . l:sep . a:key . strpart(l:line, l:close)
        call setline('.', l:new)
        call cursor(line('.'), l:close + len(l:sep) + len(a:key) + 1)
    else
        let l:text = '\cite{' . a:key . '}'
        call setline('.', strpart(l:line, 0, l:col) . l:text . strpart(l:line, l:col))
        call cursor(line('.'), l:col + len(l:text))
    endif
endfunction

" :WriterCite <query>  - search, pick, insert
function! writer#Cite(query) abort
    let l:query = trim(a:query)
    if empty(l:query)
        let l:query = input('Writer cite (author and/or title): ')
        redraw
    endif
    if empty(l:query)
        return
    endif

    echo 'Writer: Searching...'
    let l:res = s:CiteRun('search --title ' . shellescape(l:query) . ' --rows 10')
    redraw
    if has_key(l:res, 'error')
        echohl ErrorMsg | echo 'Writer: ' . l:res.error | echohl None
        return
    endif

    let s:cite_results = get(l:res, 'results', [])
    if empty(s:cite_results)
        echo 'Writer: No results for "' . l:query . '"'
        return
    endif

    let l:choices = ['Writer: results from ' . get(l:res, 'source', 'crossref')]
    let l:i = 1
    for l:item in s:cite_results
        call add(l:choices, l:i . '. ' . s:FormatResult(l:item))
        let l:i += 1
    endfor

    let l:pick = inputlist(l:choices)
    redraw
    call s:CiteChoice(l:pick)
endfunction

" :WriterCiteDoi <doi>  - skip the search, go straight to the DOI
function! writer#CiteDoi(doi) abort
    let l:doi = trim(a:doi)
    if empty(l:doi)
        echohl WarningMsg | echo 'Writer: Provide a DOI' | echohl None
        return
    endif
    let l:bib = s:BibFile()
    if empty(l:bib)
        echohl ErrorMsg | echo 'Writer: No .bib found for this document' | echohl None
        return
    endif
    let l:res = s:CiteRun('cite --doi ' . shellescape(l:doi) . ' --bib ' . shellescape(l:bib))
    if has_key(l:res, 'error')
        echohl ErrorMsg | echo 'Writer: ' . l:res.error | echohl None
        return
    endif
    call s:InsertCite(l:res.cite_key)
    echo 'Writer: \cite{' . l:res.cite_key . '}'
endfunction

" Test hook: exercise cite insertion without the network round-trip
function! writer#TestInsertCite(key) abort
    call s:InsertCite(a:key)
endfunction

" :WriterBib  - report which .bib this buffer is wired to
function! writer#ShowBib() abort
    let l:bib = s:BibFile()
    if empty(l:bib)
        echo 'Writer: no bibliography found for this document'
    else
        echo 'Writer: bibliography is ' . l:bib
    endif
endfunction

" ----------------------------------------------------------------------------
" Completion for \cite{ - local .bib only, no network
" ----------------------------------------------------------------------------

let s:bib_cache = {'path': '', 'mtime': 0, 'entries': []}

function! s:BibEntries() abort
    let l:bib = s:BibFile()
    if empty(l:bib) || !filereadable(l:bib)
        return []
    endif
    let l:mtime = getftime(l:bib)
    if s:bib_cache.path ==# l:bib && s:bib_cache.mtime == l:mtime
        return s:bib_cache.entries
    endif
    let l:res = s:CiteRun('keys --bib ' . shellescape(l:bib))
    let s:bib_cache = {'path': l:bib, 'mtime': l:mtime, 'entries': get(l:res, 'entries', [])}
    return s:bib_cache.entries
endfunction

" omnifunc: completes cite keys when the cursor is inside \cite{...}
function! writer#CiteComplete(findstart, base) abort
    if a:findstart
        let l:line = getline('.')
        let l:start = col('.') - 1
        while l:start > 0 && l:line[l:start - 1] =~# '[A-Za-z0-9_:.\-]'
            let l:start -= 1
        endwhile
        " Only complete inside a \cite-like command
        let l:before = strpart(l:line, 0, l:start)
        if l:before !~# '\\\a*cite\a*\%(\[[^]]*\]\)*{[^}]*$'
            return -3
        endif
        return l:start
    endif

    let l:matches = []
    for l:entry in s:BibEntries()
        if empty(a:base) || l:entry.key =~? '^' . escape(a:base, '\\.*$^~[]')
                    \ || l:entry.author =~? escape(a:base, '\\.*$^~[]')
                    \ || l:entry.title =~? escape(a:base, '\\.*$^~[]')
            call add(l:matches, {
                        \ 'word': l:entry.key,
                        \ 'menu': l:entry.year . ' ' . l:entry.author,
                        \ 'info': l:entry.title,
                        \ })
        endif
    endfor
    return l:matches
endfunction

function! writer#SetupCiteCompletion() abort
    if &omnifunc ==# '' || &omnifunc ==# 'writer#CiteComplete'
        setlocal omnifunc=writer#CiteComplete
    endif
endfunction

augroup writer_cite
    autocmd!
    autocmd FileType tex,plaintex,markdown,pandoc call writer#SetupCiteCompletion()
augroup END

" ============================================================================
" Keybindings
" ============================================================================

" Suggestions
nnoremap <silent> <Leader>ws :call writer#RequestSuggestions()<CR>
nnoremap <silent> <Leader>w1 :call writer#InsertSuggestion(1)<CR>
nnoremap <silent> <Leader>w2 :call writer#InsertSuggestion(2)<CR>
nnoremap <silent> <Leader>w3 :call writer#InsertSuggestion(3)<CR>

" Preview cycling
nnoremap <silent> <Leader>wn :call writer#PreviewNext()<CR>
nnoremap <silent> <Leader>wp :call writer#PreviewPrev()<CR>
nnoremap <silent> <Leader>wa :call <SID>AcceptPreview()<CR>
nnoremap <silent> <Leader>wc :call <SID>ClearPreview()<CR>

" Outline
nnoremap <silent> <Leader>wo :call writer#RefreshOutline()<CR>
nnoremap <silent> <Leader>wf :call writer#FillSection()<CR>

" Review
nnoremap <silent> <Leader>wr :call writer#RequestReview()<CR>

" Citations
nnoremap <silent> <Leader>wb :call writer#Cite('')<CR>

" Toggle
nnoremap <silent> <Leader>wt :call writer#Toggle()<CR>

" ============================================================================
" Model Selection
" ============================================================================

let s:openai_models = ['gpt-5.2', 'gpt-5', 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo', 'o1', 'o1-mini', 'o1-preview', 'o3-mini']

function! writer#SetModel(model) abort
    let l:model_file = g:writer_dir . '/model_override.json'
    let l:override = {'openai_model': a:model}
    call writefile([json_encode(l:override)], l:model_file)
    echo "Writer: Model set to " . a:model
endfunction

function! writer#GetModel() abort
    let l:model_file = g:writer_dir . '/model_override.json'
    if filereadable(l:model_file)
        let l:content = join(readfile(l:model_file), '')
        let l:override = json_decode(l:content)
        return get(l:override, 'openai_model', 'default')
    endif
    return 'default (from config)'
endfunction

function! s:ModelComplete(ArgLead, CmdLine, CursorPos) abort
    return filter(copy(s:openai_models), 'v:val =~ "^" . a:ArgLead')
endfunction

" ============================================================================
" Commands
" ============================================================================

command! WriterSuggest call writer#RequestSuggestions()
command! WriterRefresh call writer#RefreshOutline()
command! WriterFill call writer#FillSection()
command! WriterReview call writer#RequestReview()
command! WriterToggle call writer#Toggle()
command! WriterPreviewNext call writer#PreviewNext()
command! WriterPreviewPrev call writer#PreviewPrev()
command! WriterAccept call <SID>AcceptPreview()
command! WriterClear call <SID>ClearPreview()
command! -nargs=1 -complete=customlist,<SID>ModelComplete WriterModel call writer#SetModel(<q-args>)
command! WriterModelShow echo "Writer: Current model is " . writer#GetModel()
command! -nargs=* WriterCite call writer#Cite(<q-args>)
command! -nargs=1 WriterCiteDoi call writer#CiteDoi(<q-args>)
command! WriterBib call writer#ShowBib()

" Set updatetime for responsive CursorHold
if &updatetime > 1000
    set updatetime=1000
endif
