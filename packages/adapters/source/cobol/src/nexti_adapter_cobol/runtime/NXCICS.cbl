      *================================================================
      * NXCICS - THE CICS SERVICES AS SUBSTITUTES OF THE PLATFORM
      * (ADR-0056, POINT 7). A TRANSLATED PROGRAM CALLS IT WHERE IT
      * ISSUED AN EXEC CICS COMMAND; THE BYTES TRAVEL THROUGH FILES
      * UNDER /work/case AND THE HELPER (nxhelper.py) DOES THE REST:
      *   RECEIVE  THE MAP INPUT OF THE CASE INTO THE SYMBOLIC MAP
      *   SEND     THE SYMBOLIC MAP OUT, AS THE OUTPUTS OF THE CASE
      *   TEXT     A SEND TEXT, AS AN OUTPUT
      *   LINK     A CALLED PROGRAM NOT IN THE SOURCES: THE CASE SAYS
      *            WHAT IT ANSWERS; THE CALL IS LOGGED
      *   XCTL     LOGGED; THE PROGRAM ENDS
      *   RETURN   LOGGED WITH ITS TRANSID AND COMMAREA
      *   SYNC     A SYNCPOINT (COMMIT OR ROLLBACK), LOGGED
      *   FILEOP   A WRITE/REWRITE/DELETE OF A FILE, LOGGED WITH THE
      *            RECORD, SO A ROLLBACK CAN UNDO IT
      *   ASSIGN   USERID / APPLID / SYSID OF THE CASE
      *   ABEND    LOGGED; THE PROGRAM ENDS
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NXCICS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMMAND             PIC X(300).
       01  WS-NAME                PIC X(256).
       01  WS-HANDLE              PIC X(4).
       01  WS-OFFSET              PIC X(8) VALUE LOW-VALUES.
       01  WS-COUNT               PIC X(4) COMP-X.
       01  WS-FLAGS               PIC X VALUE LOW-VALUE.
       01  WS-MODE                PIC X VALUE LOW-VALUE.
       01  WS-RC                  PIC S9(8) COMP-5.
       01  WS-SIZE                PIC 9(8).
       LINKAGE SECTION.
       01  LS-OP                  PIC X(8).
       01  LS-NAME                PIC X(32).
       01  LS-AREA                PIC X(32767).
       01  LS-LEN                 PIC S9(8) COMP-5.
       PROCEDURE DIVISION USING LS-OP LS-NAME LS-AREA LS-LEN.
       0000-DISPATCH.
           EVALUATE LS-OP
              WHEN 'RECEIVE'
                 PERFORM 1000-HELPER
                 PERFORM 2000-READ-AREA
              WHEN 'SEND'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
              WHEN 'TEXT'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
              WHEN 'LINK'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
                 PERFORM 2000-READ-AREA
              WHEN 'XCTL'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
                 STOP RUN
              WHEN 'RETURN'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
              WHEN 'SYNC'
                 PERFORM 1000-HELPER
              WHEN 'FILEOP'
                 PERFORM 3000-WRITE-AREA
                 PERFORM 1000-HELPER
              WHEN 'ASSIGN'
                 PERFORM 1000-HELPER
                 PERFORM 2000-READ-AREA
              WHEN 'ABEND'
                 PERFORM 1000-HELPER
                 STOP RUN
              WHEN OTHER
                 PERFORM 1000-HELPER
           END-EVALUATE.
           GOBACK.

       1000-HELPER.
           MOVE LS-LEN TO WS-SIZE.
           STRING 'python3 /input/nx/nxhelper.py ' DELIMITED BY SIZE
                  LS-OP DELIMITED BY SPACE
                  ' ' DELIMITED BY SIZE
                  LS-NAME DELIMITED BY SPACE
                  ' ' DELIMITED BY SIZE
                  WS-SIZE DELIMITED BY SIZE
                  X'00' DELIMITED BY SIZE
                  INTO WS-COMMAND
           END-STRING.
           CALL 'SYSTEM' USING WS-COMMAND.

      * The helper left the bytes of the area in /work/case/area.bin.
       2000-READ-AREA.
           MOVE '/work/case/area.bin' TO WS-NAME.
           INSPECT WS-NAME REPLACING ALL SPACE BY X'00'.
           MOVE 1 TO WS-MODE.
           CALL 'CBL_OPEN_FILE' USING WS-NAME WS-MODE WS-FLAGS WS-FLAGS
                                      WS-HANDLE
                RETURNING WS-RC.
           IF WS-RC = 0
              MOVE LS-LEN TO WS-COUNT
              MOVE LOW-VALUES TO WS-OFFSET
              CALL 'CBL_READ_FILE' USING WS-HANDLE WS-OFFSET WS-COUNT
                                         WS-FLAGS LS-AREA
              CALL 'CBL_CLOSE_FILE' USING WS-HANDLE
           END-IF.

      * The bytes of the area go to /work/case/area.bin for the helper.
       3000-WRITE-AREA.
           MOVE '/work/case/area.bin' TO WS-NAME.
           INSPECT WS-NAME REPLACING ALL SPACE BY X'00'.
           CALL 'CBL_DELETE_FILE' USING WS-NAME.
           CALL 'CBL_CREATE_FILE' USING WS-NAME WS-MODE WS-FLAGS
                                        WS-FLAGS WS-HANDLE
                RETURNING WS-RC.
           IF WS-RC = 0
              MOVE LS-LEN TO WS-COUNT
              MOVE LOW-VALUES TO WS-OFFSET
              CALL 'CBL_WRITE_FILE' USING WS-HANDLE WS-OFFSET WS-COUNT
                                          WS-FLAGS LS-AREA
              CALL 'CBL_CLOSE_FILE' USING WS-HANDLE
           END-IF.
